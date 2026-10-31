"""Publish complete passage revisions; search joins only the active revision."""
import asyncio
import logging
from uuid import uuid4

from fastapi import HTTPException
from pymongo.errors import PyMongoError

from ..database import collection, passage_collection
from .passages import PASSAGE_SCHEMA_VERSION

logger = logging.getLogger(__name__)


async def remove_revision(resource_id, revision):
    try:
        async with asyncio.timeout(5):
            await passage_collection.delete_many({"resource_id": resource_id, "revision": revision})
    except (PyMongoError, TimeoutError) as exc:
        logger.warning("Inactive passage cleanup failed (%s)", type(exc).__name__)


async def publish_document(resource, document, *, new=False):
    resource_id = resource["_id"]
    previous = resource.get("passage_revision")
    revision = uuid4().hex
    rows = [{**p, "_id": f"{resource_id}:{revision}:{p['ordinal']}",
             "resource_id": resource_id, "revision": revision} for p in document["passages"]]
    try:
        async with asyncio.timeout(15):
            await passage_collection.insert_many(rows)
    except (PyMongoError, TimeoutError) as exc:
        await remove_revision(resource_id, revision)
        raise HTTPException(503, "Document passages could not be saved. Please try again.") from exc

    fields = {"source_pages": document["pages"], "source_sha256": document["sha256"],
              "passage_revision": revision, "passage_count": len(rows),
              "passage_schema_version": PASSAGE_SCHEMA_VERSION}
    try:
        async with asyncio.timeout(10):
            if new:
                await collection.insert_one({**resource, **fields})
            else:
                result = await collection.update_one(
                    {"_id": resource_id, "passage_revision": previous, "media_type": "document"},
                    {"$set": fields},
                )
                if not result.matched_count:
                    await remove_revision(resource_id, revision)
                    raise HTTPException(409, "The resource changed or was deleted. Reload it before reprocessing.")
    except (PyMongoError, TimeoutError) as exc:
        # A lost acknowledgement may follow a successful commit. Never delete
        # the staged revision here: it might now be the active one.
        raise HTTPException(503, "The document update could not be confirmed. Check the resource before retrying.") from exc
    if previous:
        await remove_revision(resource_id, previous)
    return fields
