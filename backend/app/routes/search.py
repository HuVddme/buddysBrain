import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import PyMongoError
from ..models import SearchQuery
from ..services.embeddings import get_embedding
from ..database import collection

from ..services.processing import run_processing
from ..services.answers import summarize_resources
from ..usage import reserve_request

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
        {"$project": {
            "title": 1,
            "summary": 1,
            "media_link": 1,
            "media_type": 1,
            "course": 1,
            "score": {"$meta": "vectorSearchScore"}
        }},
        {"$sort": {"score": -1}}
    ]

    results = []
    try:
        async with asyncio.timeout(10):
            cursor = collection.aggregate(pipeline)
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                results.append(doc)
    except (PyMongoError, TimeoutError) as exc:
        raise HTTPException(503, "The resource library is unavailable. Explore the demo or try again later.",
                            headers={"X-Error-Code": "search_unavailable"}) from exc

    try:
        summary = await run_processing(summarize_resources, results, payload.query)
    except HTTPException as exc:
        if not results or exc.status_code < 500:
            raise
        # Retrieval succeeded. Keep real saved summaries available, without
        # presenting them as a newly generated answer or verbatim source text.
        return {"summary": None, "results": results, "answer_status": "unavailable",
                "error": {"code": (exc.headers or {}).get("X-Error-Code", "ai_unavailable"),
                          "message": str(exc.detail)}}

    return {"summary": summary, "results": results}
