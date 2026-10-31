"""PostgreSQL is the durable job ledger; queue messages are only wake-ups.

No account system exists: deduplication is global to the shared public library.
Never expose source bytes, checkpoints, hashes, or worker leases in API output.
"""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from bson import ObjectId
from fastapi import HTTPException

from .. import config  # noqa: F401

MAX_ATTEMPTS = 5
LEASE_SECONDS = 300
PUBLIC_COLUMNS = "id, title, status, attempts, retryable, error_code, error_message, resource_id, created_at, updated_at, available_at, lease_until"


def enabled():
    return os.getenv('DOCUMENT_INGESTION_ENABLED', '').lower() == 'true'


class LeaseLost(Exception):
    """A newer worker owns the job; this worker must stop publishing."""


@asynccontextmanager
async def connection():
    dsn = os.getenv('INGESTION_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not dsn:
        raise HTTPException(503, 'Document processing storage is not configured.',
                            headers={'X-Error-Code': 'ingestion_unavailable'})
    try:
        # Short-lived connections work with Neon's pooled endpoint. No session locks.
        async with await psycopg.AsyncConnection.connect(
            dsn, connect_timeout=8, prepare_threshold=None, row_factory=dict_row,
        ) as conn:
            await conn.execute("SET statement_timeout = '15000'")
            await conn.execute("SET lock_timeout = '5000'")
            yield conn
    except psycopg.Error as exc:
        logging.getLogger(__name__).warning('Ingestion database failed (%s)', type(exc).__name__)
        raise HTTPException(503, 'Document processing storage is temporarily unavailable. Please try again.',
                            headers={'X-Error-Code': 'ingestion_unavailable'}) from exc


def public_job(row, *, duplicate=False):
    now = datetime.now(timezone.utc)
    resumable = row['status'] in ('queued', 'retrying') and row['available_at'] <= now
    expired = row['status'] == 'processing' and row['lease_until'] <= now
    return {
        'job_id': str(row['id']), 'title': row['title'], 'status': row['status'],
        'attempts': row['attempts'], 'duplicate': duplicate,
        'retry_available': bool(row['retryable'] and row['attempts'] < MAX_ATTEMPTS and
                                (row['status'] == 'failed' or expired or
                                 (resumable and (now - row['updated_at']).total_seconds() >= 60))),
        'error': ({'code': row['error_code'], 'message': row['error_message']}
                  if row['error_message'] else None),
        'resource_id': row['resource_id'] if row['status'] == 'succeeded' else None,
        'created_at': row['created_at'], 'updated_at': row['updated_at'],
    }


async def enqueue(contents, suffix, title, description, course):
    digest = sha256(contents).hexdigest()
    async with connection() as conn:
        # The UNIQUE constraint handles simultaneous uploads, including lost responses.
        cur = await conn.execute(f"""
            INSERT INTO ingestion_jobs
                (id, content_hash, resource_id, title, description, course, suffix, source_bytes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (content_hash) DO NOTHING RETURNING {PUBLIC_COLUMNS}
        """, (uuid4(), digest, str(ObjectId()), title, description, course, suffix, contents))
        row = await cur.fetchone()
        duplicate = row is None
        if duplicate:
            row = await (await conn.execute(
                f'SELECT {PUBLIC_COLUMNS} FROM ingestion_jobs WHERE content_hash = %s', (digest,),
            )).fetchone()
    return public_job(row, duplicate=duplicate)


async def status(job_id):
    async with connection() as conn:
        row = await (await conn.execute(
            f'SELECT {PUBLIC_COLUMNS} FROM ingestion_jobs WHERE id = %s', (job_id,),
        )).fetchone()
    if row is None:
        raise HTTPException(404, 'Document processing job not found.')
    return public_job(row)


async def retry(job_id):
    async with connection() as conn:
        row = await (await conn.execute(
            f'SELECT {PUBLIC_COLUMNS} FROM ingestion_jobs WHERE id = %s FOR UPDATE', (job_id,),
        )).fetchone()
        if row is None:
            raise HTTPException(404, 'Document processing job not found.')
        if not public_job(row)['retry_available']:
            raise HTTPException(409, 'This job cannot be retried now. Refresh its status.')
        await conn.execute("""
            UPDATE ingestion_jobs SET status = 'queued', available_at = now(),
            updated_at = now(), lease_token = NULL, lease_until = NULL,
            error_code = NULL, error_message = NULL WHERE id = %s
        """, (job_id,))
    return await status(job_id)


async def recover(job_id, contents, suffix):
    """Admin-only caller restores the original bytes and a bounded retry budget."""
    async with connection() as conn:
        row = await (await conn.execute(
            'SELECT * FROM ingestion_jobs WHERE id = %s FOR UPDATE', (job_id,),
        )).fetchone()
        if row is None:
            raise HTTPException(404, 'Document processing job not found.')
        if row['status'] != 'failed':
            raise HTTPException(409, 'Only failed jobs can be recovered. Active, completed and cancelled jobs cannot be reset.')
        if sha256(contents).hexdigest() != row['content_hash'] or suffix != row['suffix']:
            raise HTTPException(409, 'Select the original file with its original extension. Recovery cannot replace a document.')
        # Preserve immutable checkpoints, IDs and hashes for safe replay after a
        # lost Mongo acknowledgement. New attempts receive fresh lease tokens.
        await conn.execute("""UPDATE ingestion_jobs SET status = 'queued', attempts = 0,
            retryable = true, source_bytes = %s, error_code = NULL, error_message = NULL,
            lease_token = NULL, lease_until = NULL, available_at = now(), updated_at = now()
            WHERE id = %s""", (contents, job_id))
    logging.getLogger(__name__).info('Administrator recovered document job %s after %s attempts', job_id, row['attempts'])
    return await status(job_id)


async def claim(job_id=None):
    async with connection() as conn:
        # Bound crash retries too: never leave a fifth crashed attempt stuck forever.
        await conn.execute("""UPDATE ingestion_jobs SET status = 'failed', retryable = false,
            error_code = 'attempts_exhausted', error_message = 'Processing stopped after repeated interruptions. Contact the site owner.',
            lease_token = NULL, lease_until = NULL, updated_at = now()
            WHERE status = 'processing' AND lease_until < now() AND attempts >= 5""")
        row = await (await conn.execute("""
            SELECT * FROM ingestion_jobs WHERE attempts < 5 AND
            ((status IN ('queued', 'retrying') AND available_at <= now()) OR
             (status = 'processing' AND lease_until < now()))
            AND (%s::uuid IS NULL OR id = %s::uuid)
            ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
        """, (job_id, job_id))).fetchone()
        if not row:
            return None
        token = uuid4()
        await conn.execute("""UPDATE ingestion_jobs SET status = 'processing',
            attempts = attempts + 1, lease_token = %s, lease_until = now() + interval '5 minutes',
            updated_at = now() WHERE id = %s""", (token, row['id']))
        row.update(lease_token=token, attempts=row['attempts'] + 1, status='processing')
    return row


async def heartbeat(job):
    async with connection() as conn:
        cur = await conn.execute("""UPDATE ingestion_jobs SET lease_until = now() + interval '5 minutes'
            WHERE id = %s AND lease_token = %s AND status = 'processing' AND lease_until > now()
        """, (job['id'], job['lease_token']))
        if not cur.rowcount:
            raise LeaseLost()


async def checkpoint(job, result):
    async with connection() as conn:
        cur = await conn.execute("""UPDATE ingestion_jobs SET checkpoint = %s, updated_at = now()
            WHERE id = %s AND lease_token = %s AND status = 'processing' AND lease_until > now()
        """, (Jsonb(result), job['id'], job['lease_token']))
        if not cur.rowcount:
            raise LeaseLost()
    job['checkpoint'] = result


async def fail(job, message, code, retryable):
    automatically_retry = retryable and job['attempts'] < 3
    async with connection() as conn:
        await conn.execute("""UPDATE ingestion_jobs SET status = %s, error_message = %s,
            error_code = %s, retryable = %s, lease_token = NULL, lease_until = NULL,
            available_at = now() + interval '60 seconds', updated_at = now(),
            source_bytes = CASE WHEN %s THEN source_bytes ELSE NULL END
            WHERE id = %s AND lease_token = %s AND status = 'processing' AND lease_until > now()
        """, ('retrying' if automatically_retry else 'failed', message, code,
              retryable and job['attempts'] < MAX_ATTEMPTS, retryable, job['id'], job['lease_token']))


async def finish(job, publish):
    async with connection() as conn:
        row = await (await conn.execute("""SELECT id FROM ingestion_jobs WHERE id = %s
            AND lease_token = %s AND status = 'processing' AND lease_until > now() FOR UPDATE
        """, (job['id'], job['lease_token']))).fetchone()
        if not row:
            raise LeaseLost()
        # Mongo publication is idempotent. If PostgreSQL commit is lost, retry safely.
        # The row lock also serializes publication with administrative deletion.
        await publish(job)
        await conn.execute("""UPDATE ingestion_jobs SET status = 'succeeded', retryable = false,
            error_code = NULL, error_message = NULL, lease_token = NULL, lease_until = NULL,
            source_bytes = NULL, checkpoint = NULL, updated_at = now() WHERE id = %s
        """, (job['id'],))


@asynccontextmanager
async def deletion_guard(resource_id):
    async with connection() as conn:
        row = await (await conn.execute(
            'SELECT id FROM ingestion_jobs WHERE resource_id = %s FOR UPDATE', (str(resource_id),),
        )).fetchone()
        if row:
            await conn.execute("""UPDATE ingestion_jobs SET status = 'cancelled', retryable = false,
                lease_token = NULL, lease_until = NULL, source_bytes = NULL, checkpoint = NULL,
                updated_at = now() WHERE id = %s""", (row['id'],))
    # Commit the cancellation intent before deleting Mongo data. A failed delete
    # can be retried, but a lost acknowledgement must never resurrect a resource.
    yield


async def pending_ids():
    async with connection() as conn:
        # Keep abandoned input at most seven days; retain small dedup/status tombstones.
        await conn.execute("""UPDATE ingestion_jobs SET status = 'failed', retryable = false,
            source_bytes = NULL, checkpoint = NULL, lease_token = NULL, lease_until = NULL,
            error_code = 'expired', error_message = 'The processing window expired. Contact the site owner.',
            updated_at = now() WHERE status NOT IN ('succeeded', 'cancelled')
            AND updated_at < now() - interval '7 days' AND
            (status != 'processing' OR lease_until < now()) AND source_bytes IS NOT NULL""")
        rows = await (await conn.execute("""SELECT id FROM ingestion_jobs
            WHERE (status IN ('queued', 'retrying') AND available_at <= now())
               OR (status = 'processing' AND lease_until < now())
            ORDER BY created_at LIMIT 100""")).fetchall()
    return [str(row['id']) for row in rows]
