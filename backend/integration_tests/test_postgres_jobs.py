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
