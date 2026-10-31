"""Private Vercel queue function; no unauthenticated HTTP worker endpoint."""
from uuid import UUID

from vercel.queue import Message, RetryAfter, subscribe

from .services.job_dispatch import TOPIC


@subscribe(topic=TOPIC, consumer_group='document-worker', retry_after=60,
           max_concurrency=2, max_attempts=30)
async def consume(message: Message[dict[str, str]]) -> None:
    from .services import jobs
    from .services.document_worker import process_one
    if not jobs.enabled():
        raise RetryAfter(300)
    job_id = UUID(message.payload['job_id'])
    await process_one(job_id)
    state = await jobs.status(job_id)
    if state['status'] in ('queued', 'processing', 'retrying'):
        raise RetryAfter(60)
