# Original document passage retrieval

This completes the original-passage part of milestone 2. Milestone 3's PostgreSQL
jobs, duplicate-upload detection, worker and retries are documented separately
in [document ingestion](document-ingestion.md). MongoDB remains the searchable
library; per-user ownership requires a future account system.

## Deployment setup

Keep `BuddysBrainIndex` on `resources` for existing summaries, articles and images.
Create a second **Vector Search** index named exactly `BuddysBrainPassagesIndex`
on **`resource_passages`**, in the same database as `MONGO_DB`. Use
[`backend/passage-index.json`](../backend/passage-index.json). It indexes
`embedding`, 384 dimensions, cosine similarity. Wait for **Ready**.

Alternatively use the authenticated setup command below. It creates the
collection, its resource/revision cleanup index and the vector index. It does
not change an existing incompatible vector index or touch the summary index.
The MongoDB user must have permission to create search indexes. If it does not,
create the collection/index manually in Atlas using the same definition.

Set a strong `RESOURCE_ADMIN_TOKEN` privately in Vercel's backend environment
and redeploy if it was not configured already. Use the same value locally in
`backend/.env`, or enter it into the script's hidden prompt. Never put the token
in command arguments, frontend variables, Git, or chat.

From the repository root, using your backend virtual environment:

```sh
backend/.venv/bin/python backend/scripts/passage_admin.py setup --api-base https://buddysbrain.vercel.app/api
backend/.venv/bin/python backend/scripts/passage_admin.py status --api-base https://buddysbrain.vercel.app/api
```

The helper itself only needs `requests` and `python-dotenv`, not Torch, the
embedding model, MongoDB credentials or an OpenAI key. All processing runs on
the deployed backend. The status command must return `ready: true` before testing
passage search. Atlas indexing is asynchronous; newly added passages may take a
short time to appear even after a successful upload/reprocessing response.

## Reprocess existing documents without duplicate resources

Find the document's `_id` through `GET /api/resources` or Atlas. Supply the
**original** file for that ID:

```sh
backend/.venv/bin/python backend/scripts/passage_admin.py reprocess --api-base https://buddysbrain.vercel.app/api --resource-id YOUR_DOCUMENT_ID --file /absolute/path/to/original.pdf
```

This operation preserves the resource ID, title, saved summary and Cloudinary
link. It extracts and embeds the supplied original file on the server, without
another OpenAI request or Cloudinary upload. It consumes one application usage
reservation when work is needed. A repeated request for the same file and current
passage version returns `changed: false` without creating more records or using
another reservation. Once a file hash is recorded, a different file is rejected.
Legacy resources have no original hash: the administrator must select the correct
file on their first migration. This endpoint is not a file-replacement feature.

New PDF, DOCX and TXT uploads prepare passages automatically. Images, articles,
videos and unmigrated documents retain the explicitly labeled summary path.
There is no new account requirement, database migration, or full-library wipe.

## Storage and retrieval

- `resources.source_pages` retains extracted text and PDF page numbers. It is
  excluded from public resource responses; only matched excerpts appear in search.
- `resource_passages` stores overlapping text excerpts, page number, character
  offsets within that page, ordinal, embedding, parent ID and revision.
- Chunks use the embedding model's tokenizer: at most 200 tokens with 40-token
  overlap, within MiniLM's sequence limit. Exact source substrings are stored,
  rather than decoded/reworded text. DOCX and TXT use passage labels without
  invented page numbers. Embeddings are batched in groups of 16.
- A live request accepts at most 400 KB of extracted text and 256 passages. These
  limits bound synchronous work; larger documents must be split for now.
- Passage search considers 600 ANN candidates, fetches 30, joins current parent
  revisions, and selects at most eight passages, three per resource, five resources.
  Legacy summary candidates fill remaining resource slots. No absolute similarity
  cutoff is used. This is a starting retrieval policy, not a measured optimum.
- Answers receive original excerpts with `[P1]`-style labels. Generated summaries
  are labeled separately and are not supplied alongside passages for the same
  document. The UI shows excerpts/page numbers even when AI generation fails.
- Missing/unavailable passage search falls back to saved summaries with a notice
  when applicable. A failed database search is not presented as successful empty
  retrieval. The existing demo and request caps remain available.

Passages are staged under a new revision before the parent is atomically updated.
Search joins the current parent revision, excluding unfinished, stale and deleted
resources. Concurrent reprocessing uses a compare-and-set update; a losing request
gets 409. Previous revisions are cleaned up after a successful update. A process
crash or lost database acknowledgement can leave inactive passages stored; they
are not searchable. Durable cleanup/retries belong to milestone 3. Repeated new
uploads are still not deduplicated.

## Verification

```sh
cd backend
.venv/bin/python -m pytest -q
```

These tests use fake provider/database calls and cover source preservation,
token/page boundaries, publication failures, concurrency checks, protected
reprocessing, citation context and AI outage behavior. They do not prove hosted
Atlas recall or model answer quality.

After setup, reprocess the three study PDFs and repeat the fixed questions:
Cedar's permitted tools; Marigold's velocity and acceleration at two seconds;
Birch's DFS order; and Cedar's unspecified budget. Verify each answer against
the displayed original passage and page number, not just the answer wording.
