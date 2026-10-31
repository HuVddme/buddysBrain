from unittest.mock import AsyncMock

from bson import ObjectId
import pytest


@pytest.mark.parametrize("count", [101, 505])
def test_pagination_walks_past_500_without_duplicates_or_private_fields(client, db, count):
    records = [{'_id': ObjectId(f'{i:024x}'), 'title': f'Notes {i}', 'course': 'CS',
                'media_type': 'document', 'media_link': 'https://example.com/notes',
                'embedding': [0.1] * 384, 'source_pages': ['private'], 'summary': 'Long summary',
                '_deleted': i == 50} for i in range(1, count + 1)]
    class Cursor:
        def __init__(self, query, projection):
            self.rows = [r for r in records if not r['_deleted'] and
                         ('_id' not in query or r['_id'] > query['_id']['$gt'])]
            self.projection = projection

        def sort(self, field, direction):
            assert (field, direction) == ('_id', 1)
            self.rows.sort(key=lambda r: r['_id'])
            return self

        def limit(self, count):
            self.rows = self.rows[:count]
            return self

        async def to_list(self, *, length):
            assert length <= 101
            return [{k: v for k, v in r.items() if self.projection.get(k)} for r in self.rows[:length]]

    db.find.side_effect = Cursor
    seen, cursor = [], None
    for _ in range(10):
        response = client.get('/resources', params={'limit': 100, **({'after': cursor} if cursor else {})})
        assert response.status_code == 200
        page = response.json()
        assert len(page['items']) <= 100
        for item in page['items']:
            assert not {'embedding', 'source_pages', 'summary', '_deleted'} & item.keys()
            seen.append(item['_id'])
        cursor = page['next_cursor']
        if cursor is None:
            break
    assert len(seen) == len(set(seen)) == count - 1
    assert seen == sorted(seen)


@pytest.mark.parametrize('params,status', [({'limit': 0}, 422), ({'limit': 101}, 422),
                                        ({'after': 'bad-cursor'}, 400), ({'after': 'x' * 25}, 422)])
def test_invalid_page_arguments_do_not_query_storage(client, db, params, status):
    assert client.get('/resources', params=params).status_code == status
    db.find.assert_not_called()


def test_empty_page_uses_defaults_and_has_no_next_cursor(client, db):
    cursor = db.find.return_value.sort.return_value.limit.return_value
    cursor.to_list = AsyncMock(return_value=[])
    assert client.get('/resources').json() == {'items': [], 'next_cursor': None}
    db.find.return_value.sort.return_value.limit.assert_called_once_with(21)
