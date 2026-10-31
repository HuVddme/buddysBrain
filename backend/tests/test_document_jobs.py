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
