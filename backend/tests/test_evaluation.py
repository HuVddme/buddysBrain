from types import SimpleNamespace

import pytest

from scripts.evaluate import load_fixture, Retriever, score_case, usage_cost, evaluate


def test_fixed_dataset_and_gold_passages_are_valid():
    cases, passages, digest = load_fixture()
    assert len(cases) == 30 and len(passages) == 12 and len(digest) == 64
    assert sum(not c['supporting_passages'] for c in cases) == 6
    assert all(c['expected_answer'] for c in cases)


def test_scorer_distinguishes_correct_missing_and_invented_citations():
    cases, passages, _ = load_fixture()
    case = cases[2]  # CALC101 rational-expression limit = 4
    resources = Retriever(passages, 'lexical').search(case['question'])
    matching = next(p['citation'] for r in resources for p in r['passages'] if f'{r["_id"]}:{p["ordinal"]}' == 'limits:2')
    scores = score_case(case, resources, f'The limit is 4 [{matching}].')
    assert scores['retrieval_hit'] and scores['answer_fact_match_heuristic'] and scores['gold_citation_match_heuristic']
    assert scores['known_citation_fraction'] == 1
    invented = score_case(case, resources, 'The limit is 999 [P99].')
    assert not invented['answer_fact_match_heuristic'] and not invented['gold_citation_match_heuristic']
    assert invented['known_citation_fraction'] == 0
    missing = score_case(case, [], 'The limit is 4.')
    assert not missing['retrieval_hit'] and not missing['gold_citation_match_heuristic']


def test_unsupported_question_abstention_check():
    cases, _, _ = load_fixture()
    case = cases[8]
    assert score_case(case, [], 'The notes do not specify an exam date.')['abstention_heuristic']
    assert not score_case(case, [], 'The exam is on Friday.')['abstention_heuristic']


def test_cost_uses_measured_cached_and_output_tokens():
    assert usage_cost({'input_tokens': 1000, 'cached_input_tokens': 200, 'output_tokens': 100},
                      {'input': 2, 'cached_input': 1, 'output': 4}) == pytest.approx(.0022)
    assert usage_cost(None, {'input': 2, 'cached_input': 1, 'output': 4}) is None
    assert usage_cost({'input_tokens': 1}, None) is None


def test_offline_evaluation_is_reproducible_and_does_not_claim_ai_scores(tmp_path):
    args = SimpleNamespace(retriever='lexical', generate=False, limit=30, max_output_tokens=500,
                           input_usd_per_million=None, output_usd_per_million=None,
                           cached_input_usd_per_million=None, output=tmp_path/'results.json')
    first, second = evaluate(args), evaluate(args)
    assert first['fixture_sha256'] == second['fixture_sha256']
    assert [r['scores'] for r in first['cases']] == [r['scores'] for r in second['cases']]
    assert first['summary']['cases'] == 30
    assert first['summary']['generated_answers'] == 0
    assert first['summary']['estimated_cost_usd'] == 0
    assert first['summary']['answer_fact_match_rate_heuristic'] is None
    assert args.output.exists()


def test_generation_records_usage_and_stops_after_api_failure(tmp_path, monkeypatch):
    from app.services import processing
    from unittest.mock import Mock
    response = SimpleNamespace(model='test-model', usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                               prompt_tokens_details=SimpleNamespace(cached_tokens=10)),
                               choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
                                   content='A limit describes an approached value [P1].', refusal=None))])
    create = Mock(side_effect=[response, RuntimeError('private provider failure')])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(processing, 'get_ai_client', lambda: client)
    from app.services import ai
    monkeypatch.setattr(ai, 'get_ai_client', lambda: client)
    monkeypatch.setenv('OPENAI_MAX_COMPLETION_TOKENS', '500')
    args = SimpleNamespace(retriever='lexical', generate=True, limit=30, max_output_tokens=500,
                           input_usd_per_million=2, output_usd_per_million=4,
                           cached_input_usd_per_million=1, output=tmp_path/'results.json')
    report = evaluate(args)
    assert report['planned_cases'] == 30 and report['summary']['cases'] == 2
    assert report['summary']['failed_cases'] == 1 and create.call_count == 2
    assert report['cases'][0]['usage']['input_tokens'] == 100
    assert report['cases'][0]['estimated_cost_usd'] == pytest.approx(.00027)
    assert report['cases'][1]['error'] == 'RuntimeError'
    assert 'private provider failure' not in args.output.read_text()
