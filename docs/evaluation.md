# Reproducible retrieval and answer evaluation

Run from `backend` with Python 3.12. The fixture has 30 questions: 24 answerable
and six deliberately unsupported. Expected answers and supporting passage IDs
are in `evaluation/questions.json`. The corpus is the three checked-in demo
documents about limits, heaps and normalization, split into 12 paragraphs.

## No-key baseline

```bash
python -m pip install -r requirements-test.txt
python -m scripts.evaluate --output /tmp/buddy-lexical.json
```

This evaluates a deterministic TF-IDF/cosine lexical baseline, makes no AI calls,
and reports answer metrics as null. CI runs it and saves the JSON artifact.
Passing this small fixture is not evidence of production retrieval accuracy.

To compare the baseline with the application's MiniLM embedding model, install
the full dependencies (including Torch; the first run also downloads the model):

```bash
python -m pip install -r requirements.txt
python -m scripts.evaluate --retriever minilm --output /tmp/buddy-minilm.json
```

Both modes use the same paragraphs, questions, production passage grouping,
eight-passage context budget and three-passage-per-resource limit. MiniLM uses
exact local cosine ranking, not Atlas approximate vector search. These runs do
not test uploads, production chunking, Atlas index settings, or browser behavior.

## Paid answer evaluation

Configure your private `backend/.env` as for the backend, including
`OPENAI_API_KEY`, `OPENAI_MODEL` and optionally `OPENAI_REASONING_EFFORT`. Never
commit that file. Generation is explicitly opt-in:

```bash
python -m scripts.evaluate --generate --limit 30 --output /tmp/buddy-answers.json
```

This uses the actual production answer prompt and client with the lexical
baseline. Add `--retriever minilm` to evaluate embedding retrieval plus answers.
Use `--limit 1` for a configuration check. The default output budget is 500
tokens per answer; `--max-output-tokens` accepts 1–2000. Provider retries follow
the production client configuration. The run stops on the first failed case,
saves the partial report, and exits nonzero. Error reports contain exception
classes, not private provider messages. Compare `planned_cases` with `cases` and
check `failed_cases` before interpreting any averages.

The report records returned input, cached-input and output token usage. Dollar
cost remains null unless you explicitly supply current prices for your model:

```bash
python -m scripts.evaluate --generate --output /tmp/buddy-priced.json \
  --input-usd-per-million "$INPUT_RATE" \
  --cached-input-usd-per-million "$CACHED_INPUT_RATE" \
  --output-usd-per-million "$OUTPUT_RATE"
```

Set these three shell variables to your provider's rates per million tokens.
Omitting the cached-input rate uses the ordinary input rate. Estimates cover
returned usage only: failed requests or provider-side charges without returned
usage may be missing. Check provider billing for actual spend. This command
does not use the website's request allowance and does not write library data.

## Reading and comparing results

- **Retrieval hit rate:** fraction of answerable cases whose final context
  includes at least one labeled supporting passage. Unsupported cases are
  excluded. This is not passage precision or a broad retrieval benchmark.
- **Answer fact match:** regex checks against expected facts. Wording changes
  can cause false negatives; irrelevant or contradictory answers can still pass.
- **Gold citation match:** whether an answer cites at least one expected passage.
  Known-citation fraction checks that cited labels exist in that answer's context.
  Neither metric proves that each claim is supported by its citation.
- **Unsupported refusal:** a wording heuristic for acknowledging missing evidence.
  Manually check that the answer also avoids inventing the requested detail.
- **Latency:** local retrieval plus generation, with p50 and p95 in milliseconds.
  Model initialization is recorded separately as `startup_ms`. This excludes
  browser, hosting, Atlas and upload latency.
- **Cost:** estimated from returned token usage and explicitly supplied rates;
  unavailable usage or prices produce null, not zero.

Review every generated answer alongside its expected answer and cited passage.
Record whether the requested facts are correct, every factual claim is supported,
citations point to the right evidence, and unsupported details are left unanswered.
The automatic scores are screening aids, not an independent semantic judge.

For a fair comparison keep `fixture_sha256`, model, reasoning effort, output
budget and package versions fixed; change only the retriever. Reports include
these settings and the current Git commit. Repeat generation runs because model
outputs vary. Preserve the full JSON files, including failures, rather than
reporting only successful examples. Expand this small fixture with independently
written, harder documents before claiming general accuracy improvements.
