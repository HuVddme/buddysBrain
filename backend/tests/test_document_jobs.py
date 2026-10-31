import asyncio
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services import jobs, document_worker as worker
from app.routes import resources, ingestion


def job_row(**changes):
    now = datetime.now(timezone.utc)
    return dict(id=uuid4(), resource_id='507f1f77bcf86cd799439011', title='Notes',
                description='Example', course='CS', suffix='.txt', source_bytes=b'notes',
                created_at=now, updated_at=now, available_at=now, lease_until=now + timedelta(minutes=5),
                lease_token=uuid4(), checkpoint=None, attempts=1, status='processing',
                retryable=True, error_code=None, error_message=None, **changes)


def test_public_status_hides_inputs_and_leases():
    row = job_row()
    output = jobs.public_job(row)
    assert not output['retry_available']
    assert not {'source_bytes', 'checkpoint', 'lease_token', 'content_hash'} & output.keys()
    row.update(status='failed', error_message='Try again', error_code='interrupted')
    assert jobs.public_job(row)['retry_available']
    row['attempts'] = 5
    assert not jobs.public_job(row)['retry_available']


def test_upload_enqueues_without_processing(client, monkeypatch, db):
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    db.find_one.return_value = None
    enqueue = AsyncMock(return_value={'job_id': str(uuid4()), 'status': 'queued'})
    monkeypatch.setattr(jobs, 'enqueue', enqueue)
    monkeypatch.setattr(resources, 'dispatch', AsyncMock(return_value=False))
    processing = AsyncMock()
    monkeypatch.setattr(resources, 'run_processing', processing)
    response = client.post('/upload', files={'file': ('notes.txt', b'Study notes', 'text/plain')},
                           data={'title': 'Notes', 'description': 'Example', 'course': 'CS'})
    assert response.status_code == 202
    assert response.json()['dispatch_pending'] is True
    enqueue.assert_awaited_once()
    processing.assert_not_called()
    db.insert_one.assert_not_called()


def test_completed_duplicate_returns_existing_title_and_duplicate_flag(client, monkeypatch, db):
    from bson import ObjectId
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    db.find_one.return_value = {'_id': ObjectId(), 'title': 'Original title', 'description': 'Notes',
                               'course': 'CS', 'media_type': 'document', 'media_link': 'https://example.com/file'}
    enqueue = AsyncMock()
    monkeypatch.setattr(jobs, 'enqueue', enqueue)
    response = client.post('/upload', data={'title': 'New title', 'description': 'Notes', 'course': 'CS'},
                           files={'file': ('notes.txt', b'notes')})
    assert response.status_code == 200
    assert response.json()['duplicate'] is True
    assert response.json()['title'] == 'Original title'
    enqueue.assert_not_called()
    db.insert_one.assert_not_called()


@pytest.mark.parametrize('filename,content,status_code', [('empty.txt', b'', 422), ('notes.exe', b'bad', 415)])
def test_invalid_upload_never_queues(client, monkeypatch, filename, content, status_code):
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    enqueue = AsyncMock()
    monkeypatch.setattr(jobs, 'enqueue', enqueue)
    response = client.post('/upload', files={'file': (filename, content)},
                           data={'title': 'Notes', 'description': 'Example', 'course': 'CS'})
    assert response.status_code == status_code
    enqueue.assert_not_called()


def test_setup_and_reconciliation_require_admin(client, monkeypatch):
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    monkeypatch.setenv('RESOURCE_ADMIN_TOKEN', 'expected-token')
    assert client.post('/admin/ingestion/setup').status_code == 401
    assert client.post('/admin/ingestion/reconcile').status_code == 401
    assert client.get('/internal/ingestion/reconcile').status_code == 401


@pytest.mark.parametrize('authorization', [None, 'Bearer wrong', 'Basic wrong'])
def test_recovery_requires_admin_before_storage(client, monkeypatch, authorization):
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    monkeypatch.setenv('RESOURCE_ADMIN_TOKEN', 'admin')
    recover = AsyncMock()
    monkeypatch.setattr(jobs, 'recover', recover)
    response = client.post(f'/admin/ingestion/{uuid4()}/recover',
                           headers={'Authorization': authorization} if authorization else {},
                           files={'file': ('notes.txt', b'original')})
    assert response.status_code == 401
    recover.assert_not_called()


def test_recovery_dispatch_failure_keeps_saved_job(client, monkeypatch):
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    monkeypatch.setenv('RESOURCE_ADMIN_TOKEN', 'admin')
    job_id = uuid4()
    recover = AsyncMock(return_value={'job_id': str(job_id), 'status': 'queued'})
    monkeypatch.setattr(jobs, 'recover', recover)
    monkeypatch.setattr(ingestion, 'dispatch', AsyncMock(return_value=False))
    response = client.post(f'/admin/ingestion/{job_id}/recover', headers={'Authorization': 'Bearer admin'},
                           files={'file': ('notes.txt', b'original')})
    assert response.status_code == 200 and response.json()['dispatch_pending'] is True
    assert response.headers['Cache-Control'] == 'no-store'
    recover.assert_awaited_once_with(job_id, b'original', '.txt')


@pytest.mark.parametrize('filename,data,expected', [('bad.exe', b'bad', 415), ('empty.txt', b'', 422)])
def test_invalid_recovery_upload_does_not_touch_job(client, monkeypatch, filename, data, expected):
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    monkeypatch.setenv('RESOURCE_ADMIN_TOKEN', 'admin')
    recover = AsyncMock()
    monkeypatch.setattr(jobs, 'recover', recover)
    response = client.post(f'/admin/ingestion/{uuid4()}/recover', headers={'Authorization': 'Bearer admin'},
                           files={'file': (filename, data)})
    assert response.status_code == expected
    recover.assert_not_called()


def test_retry_checks_quota_before_job_or_dispatch(client, monkeypatch):
    from app.usage import limiter
    monkeypatch.setenv('DOCUMENT_INGESTION_ENABLED', 'true')
    monkeypatch.setattr(limiter, 'reserve', AsyncMock(side_effect=HTTPException(429, 'Daily limit')))
    retry = AsyncMock()
    dispatch = AsyncMock()
    monkeypatch.setattr(jobs, 'retry', retry)
    monkeypatch.setattr(ingestion, 'dispatch', dispatch)
    assert client.post(f'/ingestion/{uuid4()}/retry').status_code == 429
    retry.assert_not_called()
    dispatch.assert_not_called()


def test_retry_resumes_saved_processing_without_ai_or_embedding(monkeypatch):
    row = job_row()
    row['checkpoint'] = {'document': {'pages': [{'text': 'Notes'}]}, 'summary': 'Saved',
                         'embedding': [0.1], 'media_link': 'https://example.test/file'}
    monkeypatch.setattr(jobs, 'claim', AsyncMock(return_value=row))
    finish = AsyncMock()
    processing = AsyncMock()
    monkeypatch.setattr(jobs, 'finish', finish)
    monkeypatch.setattr(worker, 'run_processing', processing)
    assert asyncio.run(worker.process_one(row['id']))
    finish.assert_awaited_once_with(row, worker.publish)
    processing.assert_not_called()


def test_worker_keeps_empty_document_failure_out_of_library(monkeypatch):
    row = job_row()
    monkeypatch.setattr(jobs, 'claim', AsyncMock(return_value=row))
    monkeypatch.setattr(worker, 'run_processing', AsyncMock(side_effect=HTTPException(422, 'No readable text')))
    fail, finish = AsyncMock(), AsyncMock()
    monkeypatch.setattr(jobs, 'fail', fail)
    monkeypatch.setattr(jobs, 'finish', finish)
    asyncio.run(worker.process_one())
    assert fail.await_args.args[-1] is False
    finish.assert_not_called()


def test_worker_lost_lease_cannot_publish(monkeypatch):
    row = job_row()
    monkeypatch.setattr(jobs, 'claim', AsyncMock(return_value=row))
    monkeypatch.setattr(worker, 'run_processing', AsyncMock(return_value={'pages': [{'text': 'Notes'}]}))
    monkeypatch.setattr(jobs, 'checkpoint', AsyncMock(side_effect=jobs.LeaseLost()))
    finish = AsyncMock()
    monkeypatch.setattr(jobs, 'finish', finish)
    asyncio.run(worker.process_one())
    finish.assert_not_called()


def test_provider_failure_retains_checkpoint_and_is_retryable(monkeypatch):
    row = job_row()
    row['checkpoint'] = {'document': {'pages': [{'text': 'Notes'}]}}
    monkeypatch.setattr(jobs, 'claim', AsyncMock(return_value=row))
    monkeypatch.setattr(worker, 'run_processing', AsyncMock(side_effect=HTTPException(503, 'AI unavailable')))
    fail = AsyncMock()
    monkeypatch.setattr(jobs, 'fail', fail)
    asyncio.run(worker.process_one())
    assert fail.await_args.args[-1] is True
    assert row['checkpoint']['document']


def test_mongo_publication_replays_without_duplicate_rows(monkeypatch):
    import sys
    from types import SimpleNamespace
    parents, passages = {}, {}
    async def bulk_write(operations, **_):
        for operation in operations:
            passages.setdefault(operation._filter['_id'], operation._doc['$setOnInsert'])
    async def update_one(query, update, **_):
        parents.setdefault(query['_id'], update['$setOnInsert'])
    fake = SimpleNamespace(
        collection=SimpleNamespace(update_one=update_one),
        passage_collection=SimpleNamespace(bulk_write=bulk_write),
    )
    monkeypatch.setitem(sys.modules, 'app.database', fake)
    row = job_row()
    row['checkpoint'] = {'document': {'pages': [{'text': 'Notes'}], 'sha256': 'abc',
                                     'passages': [{'ordinal': 1, 'text': 'Notes', 'embedding': [0.1]}]},
                         'summary': 'Notes', 'embedding': [0.1], 'media_link': 'https://example.test/file'}
    async def run():
        await worker.publish(row)
        await worker.publish(row)
        assert len(parents) == 1 and len(passages) == 1
        resource_id = next(iter(parents))
        parents[resource_id] = {'_id': resource_id, '_deleted': True}
        await worker.publish(row)
        assert parents[resource_id] == {'_id': resource_id, '_deleted': True}
    asyncio.run(run())


def test_deleted_job_resource_is_not_readable(client, db):
    db.find_one.return_value = {'_id': '507f1f77bcf86cd799439011', '_deleted': True}
    assert client.get('/resources/507f1f77bcf86cd799439011').status_code == 404


def test_summary_vector_search_filters_tombstones(client, db):
    class Empty:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
    db.aggregate.return_value = Empty()
    client.post('/search', json={'query': 'Notes'})
    pipeline = db.aggregate.call_args.args[0]
    assert {'$match': {'_deleted': {'$ne': True}}} in pipeline
