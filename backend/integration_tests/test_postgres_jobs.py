"""Real PostgreSQL concurrency tests, isolated in a disposable schema.

Only TEST_DATABASE_URL is used; never connect to a deployment database implicitly.
Run separately from tests/, whose fixtures deliberately prohibit networking.
"""
import asyncio
import os
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
import pytest

from app.services import jobs
from fastapi import HTTPException

pytestmark = pytest.mark.skipif(not os.getenv('TEST_DATABASE_URL'), reason='Set TEST_DATABASE_URL to an isolated PostgreSQL database')


@pytest.fixture(autouse=True)
def isolated_schema(monkeypatch):
    dsn = os.environ['TEST_DATABASE_URL']
    schema = 'ingestion_test_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    monkeypatch.setenv('INGESTION_DATABASE_URL', make_conninfo(dsn, options=f'-csearch_path={schema}'))
    async def migrate():
        async with jobs.connection() as conn:
            await conn.execute((Path(__file__).resolve().parents[1] / 'migrations/001_ingestion.sql').read_text())
    asyncio.run(migrate())
    yield
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


async def upload(contents=b'original notes'):
    return await jobs.enqueue(contents, '.txt', 'Notes', 'Example', 'CS')


def test_concurrent_duplicates_have_one_record_and_one_worker():
    async def run():
        uploads = await asyncio.gather(*(upload() for _ in range(8)))
        assert len({j['job_id'] for j in uploads}) == 1
        assert sum(not j['duplicate'] for j in uploads) == 1
        claimed = await asyncio.gather(*(jobs.claim() for _ in range(8)))
        assert sum(j is not None for j in claimed) == 1
    asyncio.run(run())


def test_expired_worker_cannot_checkpoint_or_publish():
    async def run():
        await upload()
        old = await jobs.claim()
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET lease_until = now() - interval '1 second'")
        new = await jobs.claim()
        assert new['id'] == old['id'] and new['lease_token'] != old['lease_token']
        with pytest.raises(jobs.LeaseLost):
            await jobs.checkpoint(old, {'summary': 'stale'})
        async def never_publish(_):
            pytest.fail('stale worker published')
        with pytest.raises(jobs.LeaseLost):
            await jobs.finish(old, never_publish)
    asyncio.run(run())


def test_checkpoint_survives_failure_and_publish_commit_loss():
    async def run():
        created = await upload()
        first = await jobs.claim()
        await jobs.checkpoint(first, {'summary': 'saved AI response'})
        await jobs.fail(first, 'Unavailable', 'ai_unavailable', True)
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET available_at = now() - interval '1 second'")
        second = await jobs.claim()
        assert second['checkpoint']['summary'] == 'saved AI response'
        written_ids = set()
        async def lost_ack(row):
            written_ids.add(row['resource_id'])
            raise RuntimeError('lost publication acknowledgement')
        with pytest.raises(RuntimeError):
            await jobs.finish(second, lost_ack)
        async def publish(row):
            written_ids.add(row['resource_id'])
        await jobs.finish(second, publish)
        assert len(written_ids) == 1
        assert (await jobs.status(created['job_id']))['status'] == 'succeeded'
        assert await jobs.claim() is None
        async with jobs.connection() as conn:
            saved = await (await conn.execute('SELECT source_bytes, checkpoint FROM ingestion_jobs')).fetchone()
        assert saved == {'source_bytes': None, 'checkpoint': None}
    asyncio.run(run())


def test_delete_cancellation_survives_failed_mongo_delete():
    async def run():
        await upload()
        row = await jobs.claim()
        with pytest.raises(RuntimeError):
            async with jobs.deletion_guard(row['resource_id']):
                raise RuntimeError('Mongo unavailable')
        assert (await jobs.status(row['id']))['status'] == 'cancelled'
        assert await jobs.claim() is None
        with pytest.raises(jobs.LeaseLost):
            await jobs.checkpoint(row, {})
    asyncio.run(run())


def test_attempt_limit_covers_worker_crashes():
    async def run():
        created = await upload()
        for _ in range(5):
            assert await jobs.claim()
            async with jobs.connection() as conn:
                await conn.execute("UPDATE ingestion_jobs SET lease_until = now() - interval '1 second'")
        assert await jobs.claim() is None
        state = await jobs.status(created['job_id'])
        assert state['status'] == 'failed' and not state['retry_available']
    asyncio.run(run())


def test_concurrent_admin_recovery_preserves_dedup_and_fences_old_worker():
    async def run():
        original = await upload()
        old = await jobs.claim()
        await jobs.checkpoint(old, {'summary': 'saved result'})
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET status='failed', attempts=5, retryable=false")
        recovered = await asyncio.gather(*[
            jobs.recover(original['job_id'], b'original notes', '.txt') for _ in range(4)
        ], return_exceptions=True)
        assert sum(isinstance(r, dict) for r in recovered) == 1
        assert all(isinstance(r, dict) or (isinstance(r, HTTPException) and r.status_code == 409) for r in recovered)
        duplicate = await upload()
        assert duplicate['job_id'] == original['job_id'] and duplicate['duplicate']
        new = await jobs.claim(original['job_id'])
        assert new['attempts'] == 1 and new['resource_id'] == old['resource_id']
        assert new['checkpoint'] == old['checkpoint']
        with pytest.raises(jobs.LeaseLost):
            await jobs.checkpoint(old, {'summary': 'stale'})
        async with jobs.connection() as conn:
            assert (await (await conn.execute('SELECT count(*) AS count FROM ingestion_jobs')).fetchone())['count'] == 1
    asyncio.run(run())


def test_recovery_restores_expired_input_with_a_fresh_retention_window():
    async def run():
        original = await upload()
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET created_at=now()-interval '8 days', updated_at=now()-interval '8 days'")
        await jobs.pending_ids()
        assert (await jobs.status(original['job_id']))['error']['code'] == 'expired'
        await jobs.recover(original['job_id'], b'original notes', '.txt')
        assert original['job_id'] in await jobs.pending_ids()
        new = await jobs.claim(original['job_id'])
        assert bytes(new['source_bytes']) == b'original notes'
        assert new['checkpoint'] is None and new['attempts'] == 1
    asyncio.run(run())


@pytest.mark.parametrize('state', ['queued', 'processing', 'retrying', 'succeeded', 'cancelled'])
def test_recovery_cannot_reset_active_completed_or_deleted_jobs(state):
    async def run():
        original = await upload()
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET status=%s, lease_until=now()+interval '5 minutes'", (state,))
        with pytest.raises(HTTPException) as error:
            await jobs.recover(original['job_id'], b'original notes', '.txt')
        assert error.value.status_code == 409
        assert (await jobs.status(original['job_id']))['status'] == state
    asyncio.run(run())


@pytest.mark.parametrize('contents,suffix', [(b'different notes', '.txt'), (b'original notes', '.pdf')])
def test_recovery_cannot_replace_file(contents, suffix):
    async def run():
        original = await upload()
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET status='failed'")
        with pytest.raises(HTTPException) as error:
            await jobs.recover(original['job_id'], contents, suffix)
        assert error.value.status_code == 409
        assert (await jobs.status(original['job_id']))['status'] == 'failed'
    asyncio.run(run())


@pytest.mark.parametrize('retryable,attempts,retained', [(False, 1, False), (True, 5, False), (True, 1, True)])
def test_failed_job_payload_cleanup(retryable, attempts, retained):
    async def run():
        await upload()
        row = await jobs.claim()
        await jobs.checkpoint(row, {'summary': 'extracted private text'})
        async with jobs.connection() as conn:
            await conn.execute('UPDATE ingestion_jobs SET attempts=%s', (attempts,))
        row['attempts'] = attempts
        await jobs.fail(row, 'Processing failed', 'test_failure', retryable)
        async with jobs.connection() as conn:
            saved = await (await conn.execute('SELECT source_bytes, checkpoint, retryable FROM ingestion_jobs')).fetchone()
        assert (saved['source_bytes'] is not None) is retained
        assert (saved['checkpoint'] is not None) is retained
        assert saved['retryable'] is retained
        duplicate = await upload()
        assert duplicate['duplicate'] and duplicate['job_id'] == str(row['id'])
    asyncio.run(run())


def test_retention_clears_checkpoint_only_rows_and_preserves_active_lease():
    async def run():
        old = await upload()
        active = await upload(b'active document')
        async with jobs.connection() as conn:
            await conn.execute("""UPDATE ingestion_jobs SET status='failed', source_bytes=NULL,
                checkpoint='{"summary":"leftover text"}', updated_at=now()-interval '8 days' WHERE id=%s""", (old['job_id'],))
            await conn.execute("""UPDATE ingestion_jobs SET status='processing',
                lease_until=now()+interval '5 minutes', updated_at=now()-interval '8 days' WHERE id=%s""", (active['job_id'],))
        await jobs.pending_ids()
        async with jobs.connection() as conn:
            rows = await (await conn.execute('SELECT id, source_bytes, checkpoint, status FROM ingestion_jobs')).fetchall()
        by_id = {str(r['id']): r for r in rows}
        assert by_id[old['job_id']]['source_bytes'] is None
        assert by_id[old['job_id']]['checkpoint'] is None
        assert by_id[active['job_id']]['status'] == 'processing'
        assert by_id[active['job_id']]['source_bytes'] is not None
    asyncio.run(run())


def test_exhausted_crash_clears_payload_and_stale_failure_cannot_clear_new_owner():
    async def run():
        await upload()
        old = await jobs.claim()
        await jobs.checkpoint(old, {'summary': 'retained'})
        async with jobs.connection() as conn:
            await conn.execute("UPDATE ingestion_jobs SET lease_until=now()-interval '1 second'")
        new = await jobs.claim()
        await jobs.fail(old, 'stale', 'stale', False)
        async with jobs.connection() as conn:
            saved = await (await conn.execute('SELECT source_bytes, checkpoint FROM ingestion_jobs')).fetchone()
            assert saved['source_bytes'] is not None and saved['checkpoint'] is not None
            await conn.execute("UPDATE ingestion_jobs SET attempts=5, lease_until=now()-interval '1 second'")
        assert await jobs.claim() is None
        async with jobs.connection() as conn:
            saved = await (await conn.execute('SELECT source_bytes, checkpoint FROM ingestion_jobs')).fetchone()
        assert saved == {'source_bytes': None, 'checkpoint': None}
        assert (await jobs.status(new['id']))['status'] == 'failed'
    asyncio.run(run())
