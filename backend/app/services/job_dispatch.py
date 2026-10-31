"""Queue delivery is recoverable from PostgreSQL, never the source of truth."""
import asyncio
import logging
import os

TOPIC = 'document-ingestion'


async def dispatch(job_id):
    if os.getenv('INGESTION_DISPATCH', 'vercel') == 'poll':
        return True  # A separately running PostgreSQL worker owns dispatch.
    try:
        from vercel.queue import send
        async with asyncio.timeout(10):
            await send(TOPIC, {'job_id': str(job_id)}, retention=86400)
        return True
    except Exception as exc:
        logging.getLogger(__name__).warning('Document wake-up failed (%s)', type(exc).__name__)
        # The committed job + source remain safe. Retry, reconciliation, or local worker resumes it.
        return False
