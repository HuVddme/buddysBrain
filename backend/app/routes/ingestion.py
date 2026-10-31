import hmac
import os
import asyncio
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from ..services import jobs
from ..services.job_dispatch import dispatch
from ..usage import reserve_request
from ..auth import require_resource_admin


def require_ingestion():
    if not jobs.enabled():
        raise HTTPException(503, 'Background document processing is not enabled yet.')


router = APIRouter(dependencies=[Depends(require_ingestion)])
admin_router = APIRouter(dependencies=[Depends(require_resource_admin)])


@admin_router.post('/admin/ingestion/setup')
async def setup():
    async with jobs.connection() as conn:
        await conn.execute('SELECT pg_advisory_xact_lock(684202603)')
        await conn.execute((Path(__file__).resolve().parents[2] / 'migrations/001_ingestion.sql').read_text())
    return {'schema_ready': True, 'enabled': jobs.enabled()}


@router.get('/ingestion/{job_id}')
async def get_job(job_id: UUID, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return await jobs.status(job_id)


@router.post('/ingestion/{job_id}/retry', dependencies=[Depends(reserve_request)])
async def retry_job(job_id: UUID):
    state = await jobs.retry(job_id)
    state['dispatch_pending'] = not await dispatch(job_id)
    return state


async def reconcile():
    ids = await jobs.pending_ids()
    semaphore = asyncio.Semaphore(5)
    async def wake(job_id):
        async with semaphore:
            return await dispatch(job_id)
    sent = sum(await asyncio.gather(*(wake(job_id) for job_id in ids)))
    return {'pending': len(ids), 'dispatched': sent}


@router.post('/admin/ingestion/reconcile', dependencies=[Depends(require_resource_admin)])
async def admin_reconcile():
    return await reconcile()


@router.get('/internal/ingestion/reconcile')
async def cron_reconcile(authorization: str = Header(default='')):
    secret = os.getenv('CRON_SECRET', '')
    if not secret or not hmac.compare_digest(authorization, f'Bearer {secret}'):
        raise HTTPException(401, 'Scheduler credentials required.')
    return await reconcile()
