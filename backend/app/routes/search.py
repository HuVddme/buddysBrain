import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import PyMongoError
from ..models import SearchQuery
from ..services.embeddings import get_embedding
from ..database import collection, passage_collection

from ..services.processing import run_processing
from ..services.answers import summarize_resources
from ..usage import reserve_request
from ..services.retrieval import passage_pipeline, group_passages, combine_evidence

router = APIRouter()

@router.post("/search", dependencies=[Depends(reserve_request)])
async def vector_search_and_summarize(payload: SearchQuery):
    query_vector = await run_processing(get_embedding, payload.query)

    pipeline = [
        {"$vectorSearch": {
            "index": "BuddysBrainIndex",
            "path": "embedding",
            "queryVector": query_vector,
            "numCandidates": 100,
            # Short questions can be relevant to a multi-topic summary without
            # exceeding a fixed similarity score. Retrieve ranked candidates;
            # answer generation must check whether they support the question.
            "limit": 5
        }},
        {"$match": {"_deleted": {"$ne": True}}},
        {"$project": {
            "title": 1,
            "summary": 1,
            "media_link": 1,
            "media_type": 1,
            "course": 1,
            "passage_count": 1,
            "score": {"$meta": "vectorSearchScore"}
        }},
        {"$sort": {"score": -1}}
    ]

    summaries = []
    try:
        async with asyncio.timeout(10):
            cursor = collection.aggregate(pipeline)
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                summaries.append(doc)
    except (PyMongoError, TimeoutError) as exc:
        raise HTTPException(503, "The resource library is unavailable. Explore the demo or try again later.",
                            headers={"X-Error-Code": "search_unavailable"}) from exc

    passage_rows = []
    notice = None
    try:
        async with asyncio.timeout(10):
            async for row in passage_collection.aggregate(passage_pipeline(query_vector)):
                passage_rows.append(row)
    except (PyMongoError, TimeoutError) as exc:
        logging.getLogger(__name__).warning("Passage search failed (%s)", type(exc).__name__)
        passage_rows = []
        notice = "Original passages could not be searched. Any sources below are saved summaries."
    passage_results = group_passages(passage_rows)
    if not passage_results and any(r.get("passage_count", 0) for r in summaries):
        notice = "Original passages are not available in search yet. Saved summaries are shown while passage indexing is checked."
    results = combine_evidence(passage_results, summaries)
    if notice and not results:
        raise HTTPException(503, "The document search service is unavailable. Please try again later.",
                            headers={"X-Error-Code": "search_unavailable"})
    extra = {"retrieval_notice": notice} if notice else {}

    try:
        summary = await run_processing(summarize_resources, results, payload.query)
    except HTTPException as exc:
        if not results or exc.status_code < 500:
            raise
        # Original excerpts remain readable even if the AI service fails.
        return {"summary": None, "results": results, "answer_status": "unavailable", **extra,
                "error": {"code": (exc.headers or {}).get("X-Error-Code", "ai_unavailable"),
                          "message": str(exc.detail)}}

    return {"summary": summary, "results": results, **extra}
