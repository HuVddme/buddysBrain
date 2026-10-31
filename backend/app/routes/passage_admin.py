"""Small authenticated setup surface; no credentials are returned or logged."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pymongo import IndexModel
from pymongo.operations import SearchIndexModel
from pymongo.errors import PyMongoError

from ..auth import require_resource_admin
from ..database import passage_collection

router = APIRouter(prefix="/admin", dependencies=[Depends(require_resource_admin)])
INDEX_NAME = "BuddysBrainPassagesIndex"
INDEX_DEFINITION = {"fields": [{"type": "vector", "path": "embedding",
                                "numDimensions": 384, "similarity": "cosine"}]}


async def index_status():
    indexes = await passage_collection.list_search_indexes(name=INDEX_NAME).to_list(length=1)
    if not indexes:
        return {"name": INDEX_NAME, "exists": False, "ready": False}
    index = indexes[0]
    definition = index.get("latestDefinition", {})
    compatible = (index.get("type") == "vectorSearch"
                  and INDEX_DEFINITION["fields"][0] in definition.get("fields", []))
    return {"name": INDEX_NAME, "exists": True, "status": index.get("status"),
            "ready": index.get("status") == "READY" and bool(index.get("queryable")) and compatible,
            "compatible": compatible}


@router.get("/passage-index")
async def get_passage_index():
    try:
        async with asyncio.timeout(10):
            return await index_status()
    except (PyMongoError, TimeoutError) as exc:
        raise HTTPException(503, "Could not inspect the passage index. Check Atlas access and database permissions.") from exc


@router.post("/passage-index")
async def create_passage_index():
    try:
        async with asyncio.timeout(15):
            # Ensures the collection exists, and supports revision cleanup.
            await passage_collection.create_indexes([IndexModel([("resource_id", 1), ("revision", 1)])])
            status = await index_status()
            if status["exists"]:
                if not status["compatible"]:
                    raise HTTPException(409, "An incompatible passage index already exists. Review its definition in Atlas.")
                return status
            await passage_collection.create_search_index(SearchIndexModel(
                definition=INDEX_DEFINITION, name=INDEX_NAME, type="vectorSearch"))
            return {"name": INDEX_NAME, "exists": True, "ready": False, "status": "BUILDING"}
    except (PyMongoError, TimeoutError) as exc:
        raise HTTPException(503, "Could not create the passage index. Check Atlas search-index permissions or use the documented JSON setup.") from exc
