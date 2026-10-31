"""Resumable document processing, usable from Vercel Queues or a local worker."""
import asyncio
import contextlib
import logging

from bson import ObjectId
from fastapi import HTTPException
from pymongo import UpdateOne

from . import jobs
from .documents import summarize_document_text
from .embeddings import get_embedding
from .passages import prepare_document, PASSAGE_SCHEMA_VERSION
from .processing import run_processing, ProcessingError
from .storage import cloudinary

logger = logging.getLogger(__name__)


def store_source(contents, job_id, suffix):
    import cloudinary.uploader
    settings = cloudinary.config()
    if not all((settings.cloud_name, settings.api_key, settings.api_secret)):
        raise ProcessingError('File storage is not configured.', 503)
    result = cloudinary.uploader.upload(
        contents, resource_type='raw', timeout=30, overwrite=False,
        public_id=f'buddysbrain/ingestion/{job_id}{suffix}', unique_filename=False,
    )
    return result['secure_url']


async def publish(job):
    # Lazy import: Vercel inspects subscribers during builds without DB credentials.
    from ..database import collection, passage_collection
    result = job['checkpoint']
    document = result['document']
    resource_id = ObjectId(job['resource_id'])
    revision = str(job['id'])
    rows = [{**p, '_id': f'{resource_id}:{revision}:{p["ordinal"]}',
             'resource_id': resource_id, 'revision': revision} for p in document['passages']]
    async with asyncio.timeout(40):
        # Stable IDs + immutable saved checkpoint make partial/lost writes replayable.
        await passage_collection.bulk_write([
            UpdateOne({'_id': row['_id']}, {'$setOnInsert': row}, upsert=True) for row in rows
        ], ordered=False)
        resource = {
            '_id': resource_id, 'title': job['title'], 'description': job['description'],
            'course': job['course'], 'media_type': 'document', 'timestamp': job['created_at'],
            'media_link': result['media_link'], 'summary': result['summary'],
            'embedding': result['embedding'], 'source_pages': document['pages'],
            'source_sha256': document['sha256'], 'passage_revision': revision,
            'passage_schema_version': PASSAGE_SCHEMA_VERSION, 'passage_count': len(rows),
            'ingestion_job_id': revision,
        }
        # Publish the parent only after all passages exist; search joins this revision.
        await collection.update_one({'_id': resource_id}, {'$setOnInsert': resource}, upsert=True)


async def maintain_lease(job):
    while True:
        await asyncio.sleep(30)
        await jobs.heartbeat(job)


async def process_one(job_id=None):
    job = await jobs.claim(job_id)
    if not job:
        return False
    lease = asyncio.create_task(maintain_lease(job))
    logger.info('Document job %s started attempt %s', job['id'], job['attempts'])
    try:
        # Bound each attempt, including model downloads and embedding work.
        async with asyncio.timeout(210):
            saved = dict(job['checkpoint'] or {})
            if 'document' not in saved:
                saved['document'] = await run_processing(prepare_document, bytes(job['source_bytes']), job['suffix'])
                await jobs.checkpoint(job, saved)
            if 'summary' not in saved:
                text = '\n\n'.join(p['text'] for p in saved['document']['pages'])
                saved['summary'] = await run_processing(summarize_document_text, text)
                if not saved['summary'] or not saved['summary'].strip():
                    raise HTTPException(502, 'AI returned an empty summary. Please try again.')
                await jobs.checkpoint(job, saved)
            if 'embedding' not in saved:
                saved['embedding'] = await run_processing(get_embedding, saved['summary'])
                await jobs.checkpoint(job, saved)
            if 'media_link' not in saved:
                saved['media_link'] = await run_processing(store_source, bytes(job['source_bytes']), str(job['id']), job['suffix'])
                await jobs.checkpoint(job, saved)
            # Failed heartbeat must not be ignored even when the lease hasn't expired yet.
            if lease.done():
                lease.result()
            await jobs.finish(job, publish)
        logger.info('Document job %s succeeded', job['id'])
    except jobs.LeaseLost:
        logger.info('Document job %s changed owner; stopping this attempt', job['id'])
    except HTTPException as exc:
        await jobs.fail(job, str(exc.detail), (exc.headers or {}).get('X-Error-Code', 'processing_failed'),
                        exc.status_code not in (400, 413, 415, 422))
    except Exception as exc:
        # Never log provider messages, source text, or connection strings.
        logger.warning('Document job %s interrupted (%s)', job['id'], type(exc).__name__)
        await jobs.fail(job, 'Processing was interrupted. The saved upload can be retried.',
                        'processing_interrupted', True)
    finally:
        lease.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await lease
    return True
