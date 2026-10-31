from pathlib import Path
import os
import asyncio
from hashlib import sha256
import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from ..auth import require_resource_admin
from ..usage import limiter, reserve_request
from ..database import collection, passage_collection
from pymongo.errors import PyMongoError
from ..models import ResourceModel, ResourceOut
from ..services.embeddings import get_embedding
from ..utils.objectid import serialize_mongo_doc
from ..services.processing import run_processing
from ..services.ingestion import process_upload, summarize_link
from ..services.passages import prepare_document, PASSAGE_SCHEMA_VERSION
from ..services.passage_store import publish_document

router = APIRouter()
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
DOCUMENT_EXTENSIONS = {".pdf", ".txt", ".docx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


@router.post("/resources", response_model=ResourceOut, dependencies=[Depends(reserve_request)])
async def create_resource(resource: ResourceModel):
    resource_dict = resource.model_dump()
    summary, embedding = await run_processing(summarize_link, resource.media_type, resource.media_link)
    resource_dict.update(summary=summary, embedding=embedding)
    result = await collection.insert_one(resource_dict)
    created = await collection.find_one({"_id": result.inserted_id})
    return ResourceOut.model_validate(serialize_mongo_doc(created))


@router.post("/resources/bulk", response_model=list[ResourceOut])
async def create_bulk_resources(resources: list[ResourceModel]):
    if not 1 <= len(resources) <= 200:
        raise HTTPException(400, "Provide between 1 and 200 resources per request.")
    await limiter.reserve(cost=len(resources))
    resource_dicts = []
    for resource in resources:
        r_dict = resource.model_dump()
        r_dict["embedding"] = await run_processing(get_embedding, resource.summary or resource.description)
        resource_dicts.append(r_dict)
    result = await collection.insert_many(resource_dicts)
    inserted_docs = await collection.find({"_id": {"$in": result.inserted_ids}}).to_list(length=200)
    return [ResourceOut.model_validate(serialize_mongo_doc(doc)) for doc in inserted_docs]


@router.get("/resources", response_model=list[ResourceOut])
async def get_all_resources():
    resources = await collection.find({}, {"source_pages": 0}).to_list(500)
    return [ResourceOut.model_validate(serialize_mongo_doc(r)) for r in resources]


@router.get("/numResources", response_model=int)
async def get_resource_count():
    return await collection.count_documents({})


def resource_object_id(resource_id):
    if not ObjectId.is_valid(resource_id):
        raise HTTPException(400, "Invalid resource ID.")
    return ObjectId(resource_id)


@router.get("/resources/{resource_id}", response_model=ResourceOut)
async def get_resource(resource_id: str):
    resource = await collection.find_one({"_id": resource_object_id(resource_id)})
    if not resource:
        raise HTTPException(404, "Resource not found")
    return ResourceOut.model_validate(serialize_mongo_doc(resource))


@router.delete("/resources/{resource_id}", dependencies=[Depends(require_resource_admin)])
async def delete_resource(resource_id: str):
    object_id = resource_object_id(resource_id)
    result = await collection.delete_one({"_id": object_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Resource not found")
    # Search joins the parent, so a failed cleanup cannot expose deleted text.
    try:
        async with asyncio.timeout(5):
            await passage_collection.delete_many({"resource_id": object_id})
    except (PyMongoError, TimeoutError) as exc:
        logging.getLogger(__name__).warning("Deleted resource passage cleanup failed (%s)", type(exc).__name__)
    return {"message": "Resource deleted"}


async def read_upload(file):
    max_bytes = 4_000_000 if os.getenv("VERCEL") == "1" else MAX_UPLOAD_BYTES
    contents = await file.read(max_bytes + 1)
    if not contents:
        raise HTTPException(422, "The uploaded file is empty.")
    if len(contents) > max_bytes:
        limit = "4" if os.getenv("VERCEL") == "1" else "10"
        raise HTTPException(413, f"Files must be {limit} MB or smaller on this deployment.")
    return contents


@router.post("/upload", response_model=ResourceOut, dependencies=[Depends(reserve_request)])
async def upload_and_create_resource(
    file: UploadFile = File(...), title: str = Form(...),
    description: str = Form(...), course: str = Form(...),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix in DOCUMENT_EXTENSIONS:
        media_type = "document"
    elif suffix in IMAGE_EXTENSIONS:
        media_type = "image"
    else:
        raise HTTPException(415, "Supported files: PDF, DOCX, TXT, PNG, JPEG, WEBP and GIF.")
    contents = await read_upload(file)
    processed = await run_processing(process_upload, contents, suffix, media_type)
    resource_doc = ResourceModel(
        title=title, description=description, media_type=media_type,
        media_link=processed.media_link, course=course,
        summary=processed.summary, embedding=processed.embedding,
    ).model_dump()
    resource_doc["_id"] = ObjectId()
    if processed.document:
        await publish_document(resource_doc, processed.document, new=True)
    else:
        await collection.insert_one(resource_doc)
    created = await collection.find_one({"_id": resource_doc["_id"]})
    return ResourceOut.model_validate(serialize_mongo_doc(created))


@router.post("/resources/{resource_id}/passages", dependencies=[Depends(require_resource_admin)])
async def reprocess_document(resource_id: str, file: UploadFile = File(...)):
    """Admin supplies the original file; no new resource, AI call or cloud asset."""
    resource = await collection.find_one({"_id": resource_object_id(resource_id)})
    if not resource:
        raise HTTPException(404, "Resource not found")
    if resource["media_type"] != "document":
        raise HTTPException(415, "Only document resources can be reprocessed as passages.")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in DOCUMENT_EXTENSIONS:
        raise HTTPException(415, "Supported documents: PDF, DOCX and TXT.")
    contents = await read_upload(file)
    digest = sha256(contents).hexdigest()
    if resource.get("source_sha256") and resource["source_sha256"] != digest:
        raise HTTPException(409, "This is not the original file. Select the file used for this resource.")
    if (resource.get("source_sha256") == digest
            and resource.get("passage_schema_version") == PASSAGE_SCHEMA_VERSION
            and resource.get("passage_count", 0) > 0):
        return {"resource_id": resource_id, "passage_count": resource["passage_count"], "changed": False}
    await reserve_request()
    prepared = await run_processing(prepare_document, contents, suffix)
    fields = await publish_document(resource, prepared)
    return {"resource_id": resource_id, "passage_count": fields["passage_count"], "changed": True}
