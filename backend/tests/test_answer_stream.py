"""Streaming must preserve evidence, reject incomplete answers and close provider IO."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from app.routes import search
from app.services import answer_stream as stream
from app.services.processing import ProcessingError


def events(text):
    return [json.loads(block[6:]) for block in text.strip().split('\n\n')]


def test_stream_route_reserves_once_and_sends_sources_before_answer(client, db, monkeypatch):
    class Cursor:
        def __aiter__(self):
            return self
        async def __anext__(self):
            raise StopAsyncIteration
    db.aggregate.return_value = Cursor()
    reserve = AsyncMock()
    monkeypatch.setattr(search, 'reserve_request', reserve)
    async def deltas(*args):
        yield 'A heap '
        yield 'is a tree.'
    monkeypatch.setattr(stream, 'answer_deltas', deltas)
    response = client.post('/search', json={'query':'What is a heap?'}, headers={'Accept':'text/event-stream'})
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('text/event-stream')
    assert response.headers['cache-control'] == 'no-store, no-transform'
    parsed = events(response.text)
    assert [item['type'] for item in parsed] == ['sources','delta','delta','done']
    assert parsed[0]['results'] == []
    assert ''.join(item.get('text','') for item in parsed) == 'A heap is a tree.'
    reserve.assert_awaited_once()


def test_stream_limits_reject_before_retrieval(client, db, monkeypatch):
    monkeypatch.setattr(search, 'reserve_request', AsyncMock(side_effect=HTTPException(429,'Try later')))
    response = client.post('/search', json={'query':'Explain heaps'}, headers={'Accept':'text/event-stream'})
    assert response.status_code == 429
    db.aggregate.assert_not_called()
    invalid = client.post('/search', json={'query':'  '}, headers={'Accept':'text/event-stream'})
    assert invalid.status_code == 422


def test_partial_failure_keeps_sources_and_does_not_send_done(monkeypatch):
    async def deltas(*args):
        yield 'partial'
        raise RuntimeError('private provider diagnostic')
    monkeypatch.setattr(stream, 'answer_deltas', deltas)
    async def exercise():
        return ''.join([item async for item in stream.search_events([{'title':'Evidence'}], 'q', {'retrieval_notice':'Summary only'})])
    result = events(asyncio.run(exercise()))
    assert [item['type'] for item in result] == ['sources','delta','error']
    assert result[0]['results'] == [{'title':'Evidence'}]
    assert result[0]['retrieval_notice'] == 'Summary only'
    assert 'private provider diagnostic' not in str(result)


def test_disconnect_cancels_provider_work_and_closes_generator(monkeypatch):
    closed = []
    async def deltas(*args):
        try:
            yield 'partial'
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    monkeypatch.setattr(stream, 'answer_deltas', deltas)
    async def exercise():
        source = stream.search_events([], 'q', {})
        await anext(source)
        await anext(source)
        task = asyncio.create_task(anext(source))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await source.aclose()
    asyncio.run(exercise())
    assert closed == [True]


@pytest.mark.parametrize('finish,text,ok', [('stop','Answer',True), ('length','Partial',False), (None,'Partial',False), ('stop',' ',False)])
def test_provider_completion_requires_text_and_stop_and_closes_resources(monkeypatch, finish, text, ok):
    closed = []
    class FakeStream:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append('stream')
        def __aiter__(self):
            async def chunks():
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text,refusal=None),finish_reason=finish)])
            return chunks()
    create = AsyncMock(return_value=FakeStream())
    class FakeClient:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))
        async def __aenter__(self): return self
        async def __aexit__(self, *args): closed.append('client')
    factory = Mock(return_value=FakeClient())
    monkeypatch.setattr(stream,'AsyncOpenAI',factory)
    monkeypatch.setenv('OPENAI_API_KEY','test-only')
    async def exercise(): return [part async for part in stream.answer_deltas([], 'Question')]
    if ok:
        assert asyncio.run(exercise()) == [text]
    else:
        with pytest.raises(ProcessingError): asyncio.run(exercise())
    assert closed == ['stream','client']
    assert create.call_args.kwargs['stream'] is True
    assert factory.call_args.kwargs['timeout'] == 30
