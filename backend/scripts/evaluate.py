"""Fixed-corpus retrieval/answer evaluation. Paid generation requires --generate.

Run from backend: python -m scripts.evaluate --output /tmp/buddy-evaluation.json
This isolates retrieval and answers; it does not benchmark Atlas or ingestion.
"""
import argparse
from collections import Counter
from contextlib import nullcontext
from datetime import datetime, timezone
from hashlib import sha256
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import time
import unicodedata
from unittest.mock import patch

from app.services.retrieval import group_passages, MAX_CONTEXT_PASSAGES

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS = ROOT / 'backend/evaluation/questions.json'
CORPUS = ROOT / 'frontend/src/demo'
DOCS = ('limits', 'heaps', 'normalization')


def load_fixture():
    raw = QUESTIONS.read_bytes()
    dataset = json.loads(raw)
    digest = sha256(raw)
    passages = []
    for name in DOCS:
        content = (CORPUS / f'{name}.txt').read_bytes()
        digest.update(content)
        text = content.decode('utf-8')
        title = text.splitlines()[0]
        for ordinal, paragraph in enumerate(text.strip().split('\n\n')[1:], 1):
            passages.append({'id': f'{name}:{ordinal}', 'document': name, 'ordinal': ordinal,
                             'title': title, 'text': paragraph})
    known = {p['id'] for p in passages}
    ids = [c['id'] for c in dataset['cases']]
    if len(ids) != len(set(ids)) or len(ids) != 30:
        raise ValueError('Expected 30 uniquely identified evaluation cases.')
    for case in dataset['cases']:
        if not set(case['supporting_passages']) <= known:
            raise ValueError(f'Unknown supporting passage in {case["id"]}')
        for alternatives in case['expected_patterns']:
            for pattern in alternatives:
                re.compile(pattern)
    return dataset['cases'], passages, digest.hexdigest()


def tokens(text):
    return re.findall(r'\w+', unicodedata.normalize('NFKC', text).lower())


class Retriever:
    def __init__(self, passages, kind):
        self.passages, self.kind = passages, kind
        if kind == 'minilm':
            from app.services.embeddings import get_embedding_model
            self.model = get_embedding_model()
            self.vectors = self.model.encode([p['text'] for p in passages], normalize_embeddings=True,
                                             show_progress_bar=False)
        else:
            counts = [Counter(tokens(p['text'])) for p in passages]
            df = Counter(word for row in counts for word in row)
            self.idf = {word: math.log((1 + len(counts)) / (1 + count)) + 1 for word, count in df.items()}
            self.vectors = [self.vector(row) for row in counts]

    def vector(self, counts):
        values = {word: count * self.idf.get(word, 0) for word, count in counts.items()}
        norm = math.sqrt(sum(x * x for x in values.values())) or 1
        return {word: value / norm for word, value in values.items()}

    def search(self, question):
        if self.kind == 'minilm':
            query = self.model.encode(question, normalize_embeddings=True, show_progress_bar=False)
            scores = [float(vector @ query) for vector in self.vectors]
        else:
            query = self.vector(Counter(tokens(question)))
            scores = [sum(value * query.get(word, 0) for word, value in vector.items()) for vector in self.vectors]
        ranked = sorted(zip(self.passages, scores), key=lambda x: (-x[1], x[0]['id']))
        # Same grouping, per-resource limits and citation assignment as production.
        rows = [{'ordinal': p['ordinal'], 'text': p['text'], 'page': None, 'score': score,
                 'resource': {'_id': p['document'], 'title': p['title'], 'media_type': 'document',
                              'media_link': f'fixture://{p["document"]}'}} for p, score in ranked[:30]]
        return group_passages(rows)


def score_case(case, resources, answer):
    citations = {p['citation']: f'{r["_id"]}:{p["ordinal"]}' for r in resources for p in r.get('passages', [])}
    expected = set(case['supporting_passages'])
    hit = bool(expected & set(citations.values())) if expected else None
    scores = {'retrieval_hit': hit, 'answer_fact_match_heuristic': None,
              'gold_citation_match_heuristic': None, 'known_citation_fraction': None,
              'abstention_heuristic': None}
    if answer is None:
        return scores
    normalized = unicodedata.normalize('NFKC', answer)
    cited = set(re.findall(r'\bP\d+\b', answer))
    scores['known_citation_fraction'] = len(cited & citations.keys()) / len(cited) if cited else None
    if expected:
        scores['answer_fact_match_heuristic'] = all(any(re.search(p, normalized, re.I) for p in alternatives)
                                                     for alternatives in case['expected_patterns'])
        scores['gold_citation_match_heuristic'] = bool(expected & {citations[c] for c in cited if c in citations})
    else:
        scores['abstention_heuristic'] = bool(re.search(
            r'not (?:specif|provid|stat|mention|identif)|does(?:n.t| not) (?:specif|provid|stat|mention|identif)|'
            r'(?:can.t|cannot|can not) (?:determine|tell|identify|answer)|no (?:information|detail|date|name)|'
            r'(?:isn.t|aren.t|is not|are not) (?:given|included|listed|specified|provided)|insufficient', normalized, re.I))
    return scores


def usage_cost(usage, rates):
    if usage is None or rates is None:
        return None
    cached = min(usage['input_tokens'], usage['cached_input_tokens'])
    return ((usage['input_tokens'] - cached) * rates['input'] + cached * rates['cached_input'] +
            usage['output_tokens'] * rates['output']) / 1_000_000


def summarize(rows, generated, rates):
    def mean(key):
        values = [r['scores'][key] for r in rows if r['scores'][key] is not None]
        return statistics.mean(values) if values else None
    latencies = sorted(r['latency_ms'] for r in rows)
    costs = [r['estimated_cost_usd'] for r in rows]
    return {'cases': len(rows), 'generated_answers': sum(r['answer'] is not None for r in rows),
            'failed_cases': sum(r['error'] is not None for r in rows),
            'retrieval_hit_rate': mean('retrieval_hit'),
            'answer_fact_match_rate_heuristic': mean('answer_fact_match_heuristic'),
            'gold_citation_match_rate_heuristic': mean('gold_citation_match_heuristic'),
            'known_citation_fraction_mean': mean('known_citation_fraction'),
            'unsupported_refusal_rate_heuristic': mean('abstention_heuristic'),
            'latency_p50_ms': statistics.median(latencies),
            'latency_p95_ms': latencies[math.ceil(len(latencies) * .95) - 1],
            'estimated_cost_usd': sum(costs) if all(c is not None for c in costs) else None,
            'cost_basis': 'No AI calls' if not generated else ('Supplied per-million-token rates; returned usage only' if rates else 'Rates not supplied; inspect token usage'),
            'manual_answer_and_citation_review_required': generated}


def evaluate(args):
    cases, passages, fingerprint = load_fixture()
    startup = time.perf_counter()
    retriever = Retriever(passages, args.retriever)
    startup_ms = (time.perf_counter() - startup) * 1000
    rates = None
    if args.input_usd_per_million is not None:
        rates = {'input': args.input_usd_per_million, 'output': args.output_usd_per_million,
                 'cached_input': args.cached_input_usd_per_million if args.cached_input_usd_per_million is not None else args.input_usd_per_million}
    records, model = [], None
    if args.generate:
        from app.services import ai, answers
        from app.services.processing import get_ai_client
        os.environ['OPENAI_MAX_COMPLETION_TOKENS'] = str(args.max_output_tokens)
        client = get_ai_client()
        create = client.chat.completions.create
        model = os.getenv('OPENAI_MODEL', ai.DEFAULT_MODEL)
        def recorded_create(**kwargs):
            response = create(**kwargs)
            usage = getattr(response, 'usage', None)
            details = getattr(usage, 'prompt_tokens_details', None)
            records.append({'model': response.model, 'input_tokens': usage.prompt_tokens,
                            'output_tokens': usage.completion_tokens,
                            'cached_input_tokens': getattr(details, 'cached_tokens', 0) or 0} if usage else None)
            return response
        context = patch.object(client.chat.completions, 'create', side_effect=recorded_create)
    else:
        context = nullcontext()
    rows = []
    with context:
        for case in cases[:args.limit]:
            started = time.perf_counter()
            resources = retriever.search(case['question'])
            retrieval_ms = (time.perf_counter() - started) * 1000
            answer, error, usage = None, None, None
            before = len(records)
            if args.generate:
                try:
                    answer = answers.summarize_resources(resources, case['question'])
                except Exception as exc:
                    # Provider errors may contain secrets; report only the class.
                    error = type(exc).__name__
                usage = records[-1] if len(records) > before else None
            scores = score_case(case, resources, answer)
            rows.append({**case, 'answer': answer, 'resources': resources, 'scores': scores,
                         'error': error, 'usage': usage, 'retrieval_ms': retrieval_ms,
                         'latency_ms': (time.perf_counter() - started) * 1000,
                         'estimated_cost_usd': usage_cost(usage, rates) if args.generate else 0})
            if error:
                break  # Do not repeatedly call an unavailable or misconfigured API.
    try:
        commit = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = None
    versions = {}
    for package in ('openai', 'sentence-transformers'):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    report = {'schema_version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
              'planned_cases': args.limit, 'package_versions': versions,
              'fixture_sha256': fingerprint, 'git_commit': commit, 'retriever': args.retriever,
              'embedding_model': 'all-MiniLM-L6-v2' if args.retriever == 'minilm' else None,
              'max_context_passages': MAX_CONTEXT_PASSAGES, 'model': model,
              'reasoning_effort': os.getenv('OPENAI_REASONING_EFFORT', 'none') if args.generate else None,
              'max_output_tokens': args.max_output_tokens if args.generate else None,
              'rates_usd_per_million': rates, 'startup_ms': startup_ms,
              'scope': 'Exact local retrieval over 12 fixed paragraphs; not Atlas ANN, upload processing, or end-to-end site latency.',
              'summary': summarize(rows, args.generate, rates), 'cases': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--retriever', choices=['lexical', 'minilm'], default='lexical')
    parser.add_argument('--generate', action='store_true', help='Call the configured paid AI API for answers')
    parser.add_argument('--limit', type=int, default=30, choices=range(1, 31), metavar='1..30')
    parser.add_argument('--max-output-tokens', type=int, default=500, choices=range(1, 2001), metavar='1..2000')
    parser.add_argument('--output', type=Path, required=True)
    for name in ('input', 'cached-input', 'output'):
        parser.add_argument(f'--{name}-usd-per-million', type=float)
    args = parser.parse_args()
    if (args.input_usd_per_million is None) != (args.output_usd_per_million is None):
        parser.error('Supply both input and output prices, or neither.')
    if args.cached_input_usd_per_million is not None and args.input_usd_per_million is None:
        parser.error('Cached-input pricing also requires input and output prices.')
    for value in (args.input_usd_per_million, args.output_usd_per_million, args.cached_input_usd_per_million):
        if value is not None and (not math.isfinite(value) or value < 0):
            parser.error('Prices must be finite and nonnegative.')
    try:
        report = evaluate(args)
    except Exception as exc:
        raise SystemExit(f'Evaluation could not complete ({type(exc).__name__}). Check dependencies and private backend configuration.') from None
    print(json.dumps(report['summary'], indent=2))
    if report['summary']['failed_cases']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
