# Development and deployment guide

Setup, configuration, API behavior, and engineering notes for contributors. For an overview of the study experience, see the [project README](../README.md).

## Tech Stack

- **Frontend**: React, TypeScript, Tailwind CSS
- **Backend**: FastAPI, MongoDB (with vector search capabilities)
- **AI Model**: OpenAI GPT-6 Luna
- **Deployment**: Vercel Services configuration for this version's frontend and API; a separate frontend-only demo deployment is also supported.

## Repository layout

```text
frontend/             React/Vite app, demo content and frontend tests
backend/
  app/routes/         HTTP validation, database operations and responses
  app/services/       Reusable ingestion, AI, embedding and storage operations
  app/utils/          URL safety and MongoDB serialization helpers
  tests/              API, failure-handling and service tests
docs/                 Architecture and deployment decisions
vercel.json           Public routing and configuration for web + api
```

See [architecture and deployment decisions](architecture.md). The API and
frontend stay in one repository and can also run independently. Document uploads
can use the durable PostgreSQL/Vercel Queue worker described in the
[ingestion guide](document-ingestion.md). Other media retain request-time
processing in a thread pool.

## Getting Started

### Prerequisites

- Python 3.12 for the backend deployment (the isolated test suite also runs on 3.11)
- Node.js and npm for the frontend
- MongoDB with vector search indexes
- OpenAI API key

### Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/HuVddme/buddysBrain.git
cd buddysBrain/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Enter your own database, OpenAI and Cloudinary settings in the backend `.env`.
The template lists every variable. Keep the real file private and out of Git.
Hosting environment variables take precedence over this local file.

```
OPENAI_API_KEY=your_openai_api_key
CLOUDINARY_CLOUD_NAME=your_cloud_name
CLOUDINARY_API_KEY=your_api_key
CLOUDINARY_API_SECRET=your_api_secret
```

### Explore the demo locally

The frontend is independently runnable. No backend or environment file is needed:

```bash
cd frontend
npm ci
npm run dev
```

Open the displayed localhost address and choose **Explore demo**. Sample lessons
cover calculus limits, binary heaps and database normalization. All six answers
are hand-authored saved examples; their supporting quotations come directly from
the bundled notes. They are not live AI output or evaluation results. The demo
never calls the backend or uploads content. It offers fixed questions, not an
unrestricted chatbot. Fonts are bundled with the frontend.

### Deploy your own frontend demo

In your own Vercel account, import **HuVddme/buddysBrain** as a **new project**:

| Setting | Value |
| --- | --- |
| Root Directory | `frontend` |
| Framework | Vite |
| Build Command | `npm run build` |
| Output Directory | `dist` |
| Production Branch | `main` |
| `VITE_ENABLE_LIVE` | `false` (also the default when unset) |
| `VITE_API_BASE_URL` | Leave unset for demo-only deployment |

The included `vercel.json` makes direct visits to `/ask` and `/submit` work.
No API key belongs in Vercel's frontend variables. This project can host the demo
while your Railway account is pending. The independent production site is [buddysbrain.vercel.app](https://buddysbrain.vercel.app/). See
[Vercel's Vite guide](https://vercel.com/docs/frameworks/frontend/vite).

### Deploy frontend and backend together on Vercel

Alternatively, import **HuVddme/buddysBrain** with Root Directory set to the repository
root (`.`). The root `vercel.json` configures Vercel Services, currently in
[Beta](https://vercel.com/docs/services):

| Service | Public paths | Runtime |
| --- | --- | --- |
| `api` | `/api/*`, including `/api/health` and `/api/docs` | Python 3.12 / FastAPI |
| `web` | All remaining paths, including `/ask` and `/submit` | Vite static frontend |

The browser calls the public API with `VITE_API_BASE_URL=/api`. No internal
service bindings are needed: this frontend has no server-side function calling
another service. Bindings exist only in functions at runtime, not in Vite's
browser code or during its build. The FastAPI wrapper mounts the existing app
at `/api`, matching Vercel's preserved request paths. Other hosts can continue
running `app.main:app` without the prefix.

Configure these values privately in your new Vercel project's environment settings:

- Backend: the MongoDB, Cloudinary, OpenAI, admin-token and quota settings listed
  in `backend/.env.example`. Never prefix secrets with `VITE_`.
- Frontend: `VITE_API_BASE_URL=/api` and `VITE_ENABLE_LIVE=true` when ready to
  enable the live forms. Rebuild after changing these build-time values.
- `FRONTEND_ORIGINS`: your own frontend's exact origin. Same-origin `/api` calls
  do not need cross-origin permission, but this still governs other browser clients.

You can reuse your own existing MongoDB Atlas cluster. Check the selected
database's `resources` collection has the `BuddysBrainIndex` vector search index
on `embedding`, compatible with the existing 384-dimensional MiniLM vectors;
also check database-user permissions and network access from the deployment.
The MongoDB account and cluster alone do not create the vector search index.
The backend also needs permission to create the quota collection's TTL index.

Both services are public under the routes above even if `VITE_ENABLE_LIVE=false`:
that flag hides frontend forms, not the backend. To block expensive API work,
set `LIVE_REQUESTS_PER_DAY=0`. Existing deletion authentication still applies.

The backend's `pyproject.toml` selects CPU-only PyTorch wheels on Linux through
uv, and the embedding model loads lazily into Vercel's writable temporary cache.
The cache is ephemeral; new instances may download the model again. ML dependencies
can exceed the standard Python bundle limit. Check
[large-function support and current limits](https://vercel.com/docs/functions/limitations)
for your project; eligible existing projects can enable it with
`VERCEL_SUPPORT_LARGE_FUNCTIONS=1`. The hosted build, bundle size, memory usage
and cold-start latency still need verification with the actual deployment.

Uploads are capped at **4 MB** on Vercel to leave multipart overhead beneath
its 4.5 MB request-body limit. Other hosts retain the existing 10 MiB file limit.
Larger uploads would require a separate direct-to-storage upload flow.

With the Vercel CLI and service dependencies installed, run `vercel dev` from
the repository root to exercise both services together. Check `/api/health`
for liveness, then a real upload and question to verify MongoDB, vector retrieval
and AI access. Health alone does not check external services. Local automated
tests use mocked services and do not prove a hosted deployment works.

### Enable live questions and uploads with a separate backend

1. Deploy your own backend with MongoDB/vector index, OpenAI and Cloudinary values.
2. Set backend `FRONTEND_ORIGINS` to your frontend's exact origin, such as
   `https://your-project.vercel.app`. Comma-separate additional approved origins.
   Include `http://localhost:5173` when you need local development. CORS is a
   browser policy, not authentication; direct API requests remain public.
3. Set frontend `VITE_API_BASE_URL` to **your** backend URL and
   `VITE_ENABLE_LIVE=true`, then rebuild/redeploy. For local development, put
   those two public values in the frontend `.env` and restart Vite.
4. Check one real search and upload before inviting visitors. Do not connect
   this version to the teammate's production backend.

The default view remains the demo even when live mode is enabled. **Ask live**
allows custom questions, and live users can open the upload page. With live mode
disabled, neither page offers a form that would call an unconfigured backend.

Live requests distinguish backend connectivity, timeouts, provider access/usage
problems and application usage limits. Questions and form fields survive failures.
If retrieval succeeds but AI generation fails, `/search` returns HTTP 200 with
`summary: null`, `answer_status: "unavailable"`, an `error` containing a safe code
and message, and the retrieved `results`. Those results are labeled **saved
resource summaries** for legacy resources; processed documents instead show original
extracted passages with citation labels and PDF page numbers. Demo passages are real
excerpts of the bundled sample notes. If retrieval
itself fails, the API returns an error rather than an unsupported fallback answer.

New document uploads retain extracted text and token-bounded overlapping passages.
Search retrieves original passages and uses legacy summary candidates for resources
not yet migrated. Returned resources are candidates, not proof of relevance: answers
must cite supporting passages or explicitly identify a saved summary and acknowledge
missing information. There is no uncalibrated absolute similarity cutoff.

**One-time setup:** create `BuddysBrainPassagesIndex` on `resource_passages`, then
reprocess existing PDFs by resource ID with the authenticated helper. Existing
summaries continue working during migration. See the
[passage setup and reprocessing guide](passage-retrieval.md) for the exact index
definition, commands, limits and remaining milestone-3 work. Reprocessing does not
create duplicate resources or re-upload files to Cloudinary.

### Browsing the resource library

`GET /api/resources?limit=20` returns `{ "items": [...], "next_cursor": "..." }`.
Pass `next_cursor` as `after` on the next request; stop when it is `null`. The page
size is 1–100 (default 20), ordered by ascending Mongo `_id`, excluding deletions.
List items contain only `_id`, title, course, media type/link, timestamp and passage
count. Read `/api/resources/{id}` for the full saved summary and description.
This replaces the old bare array capped at 500 entries; external callers must
read `items` and follow the cursor. The current frontend uses search and resource
counts and does not depend on the old array. This is not a snapshot: records added
or deleted during traversal can change subsequent pages; restart to refresh.

### Live usage allowance

The backend trims questions and requires 1–2,000 characters. Resource titles and
courses require 1–200 characters, and descriptions require 1–4,000, after trimming.
These metadata rules apply to single links, bulk links, and document/image uploads.
Link submissions accept only `article` or `video` and HTTP/HTTPS URLs up to 2,048
characters; documents and images use the upload endpoint. Unknown JSON fields,
including caller-supplied summaries, embeddings and timestamps, are rejected.
Invalid question/metadata requests return HTTP 422 before quota reservation or
processing. Existing library records remain readable under their original schema.

`LIVE_REQUESTS_PER_MINUTE=12` and `LIVE_REQUESTS_PER_DAY=100` are the backend
global defaults, shared across all visitors. Each search,
link submission or file upload reserves one unit before expensive work; a bulk
submission reserves one unit per resource. Set either limit to `0` to block live
work. Invalid settings or an unavailable quota database fail closed.

Public requests also have persistent per-visitor limits, checked **before** global
reservation so a blocked visitor cannot keep spending the shared allowance:

| Setting | Default |
| --- | --- |
| `VISITOR_REQUESTS_PER_MINUTE` | 4 |
| `VISITOR_REQUESTS_PER_DAY` | 20 |
| `VISITOR_SUBMISSIONS_PER_MINUTE` | 2 |
| `VISITOR_SUBMISSIONS_PER_DAY` | 5 |

Searches, link/file submissions and public job retries count toward visitor limits.
Submissions and retries also count toward the stricter submission limits. Trusted
admin operations use the global allowance only. HTTP 429 responses identify the
limit and include `Retry-After`; the frontend already displays these messages.

Without accounts, a visitor means an IP/network: shared Wi-Fi/NAT users share a
bucket, and IPv6 addresses are grouped by /64. This discourages abuse but cannot
identify someone who switches networks. The backend uses Vercel's
[`x-vercel-forwarded-for` header](https://vercel.com/docs/headers/request-headers#x-vercel-forwarded-for)
only when running on Vercel. Other deployments use the direct peer address and
ignore forwarded headers; configure any trusted reverse proxy at the server layer.
Missing/malformed platform identity fails closed instead of choosing an arbitrary
header. Non-IP local transports share one fallback bucket.

Only an HMAC of the normalized address is stored in quota keys, not the raw IP.
`VISITOR_RATE_LIMIT_SECRET` can supply a dedicated secret; otherwise the backend
uses the existing `RESOURCE_ADMIN_TOKEN`. With neither set, public requests fail
closed. Changing the hashing secret resets visitor buckets but not global caps.
No additional environment change is needed on the existing deployment.

Counters live in the separate MongoDB `usage_limits` collection, with conditional
atomic updates on unique `_id` keys. They survive restarts and are shared by
replicas using the same database. The app creates a TTL index on `expires_at`;
the database user needs permission to create that index. Old counters expire after
their window plus one day, and delayed TTL cleanup does not affect resets.

These are fixed calendar-minute and UTC-day windows, not rolling limits. Attempts,
including processing failures, count; a later rejected reservation can still
consume earlier visitor/minute reservations. Limits are checked before processing, and exhausted
allowances return HTTP 429 with `Retry-After`. Browser cancellations do not refund
reservations or guarantee cancellation of backend work already started.

This bounds accepted operations, **not dollar spend**: token usage varies and SDK
retries may make additional provider calls. There is no account-based fairness or
concurrency cap yet. Keep conservative limits for the initial public launch and
measure real usage before raising them. The quota tests use an atomic in-memory
Mongo test double; multi-process Mongo behavior and TTL cleanup still need a live
integration check with your own database.

### AI model configuration

All document, image, article, YouTube and search summaries use the shared Chat
Completions client. Defaults work without adding new variables to an existing
backend `.env`:

```dotenv
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=none
```

Keep your existing `OPENAI_API_KEY` private on the backend. Your OpenAI project
must have access to Luna and available API quota. A model change alone does not
fix missing credentials, exhausted quota or an unavailable backend.

The default preserves non-reasoning behavior and temperature 0.3. Output budgets
remain 300 tokens for article/video summaries and 500 for documents, images and
answers, now using `max_completion_tokens`. Empty, refused and truncated responses
return errors instead of being stored. For a later reasoning comparison, set
`OPENAI_REASONING_EFFORT=low` and `OPENAI_MAX_COMPLETION_TOKENS=4096`; temperature is
omitted when reasoning is enabled. The override applies to every task and includes
both reasoning and visible output tokens, so raising it can increase cost/latency.
Restart the backend after changing settings. Other model IDs require checking
that model's parameter and image-input compatibility first.

Text prompts, including questions and instructions, are limited to 400,000 UTF-8
bytes. This replaces the old 100,000-token estimate with an application size limit,
not an exact Luna token count; non-English text can reach the limit sooner.
It avoids unsupported tokenizer mappings and tokenizer downloads during requests.
Image data is subject to the existing upload size limit separately.

MongoDB vectors and the `all-MiniLM-L6-v2` embedding model are unchanged; existing
resources need no reindexing. The standalone search utility uses the same client:
run `python -m app.services.cli_search` from the backend directory with
its `resources.json` input in that working directory.

Migration references: [Luna model](https://developers.openai.com/api/docs/models/gpt-6-luna),
[parameter compatibility](https://developers.openai.com/api/docs/guides/latest-model?model=gpt-6-astra),
and [Chat Completions output limits](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
Mocked tests verify request compatibility and failure handling; live answer quality,
latency and cost still need measurement with your own configured services.

### Starting the Server

From `backend`, with the virtual environment active:

```bash
uvicorn app.main:app --reload --port 8000
```

For the frontend, enter `frontend`, run `npm ci`, copy
`.env.example` to `.env`, and run `npm run dev`. Set `VITE_API_BASE_URL` to your
backend address and set `VITE_ENABLE_LIVE=true` only for live use. Rebuild the
frontend when these values change. No secret belongs
in a `VITE_*` variable.

### First round of improvements

- Bulk imports (`POST /api/resources/bulk`) require the same admin bearer token
  as deletion. Send an array of 1–200 objects with only `title` (1–200 characters),
  `description` (1–4000), `course` (1–200), `media_type` (`article` or `video`), and
  `media_link` (an HTTP/HTTPS URL up to 2048 characters). Text is trimmed and must
  not be blank. Documents and images must use `/api/upload`.
  Supplied summaries, embeddings, timestamps and unknown fields are rejected.
  The backend generates summaries from fetched articles or YouTube transcripts
  using the normal URL protections and timeouts, and generates its own embeddings.
  Processing must succeed for every item before any records are inserted; database
  insertion is not transactional and this endpoint does not provide retry deduplication.
  Existing callers that imported precomputed summaries must switch to this format.
- Cloudinary reads your backend environment variables instead of committed credentials.
- Deletion requires `Authorization: Bearer <RESOURCE_ADMIN_TOKEN>`. Generate a long
  random token locally using the command in `.env.example`. Keep it exclusively
  in trusted administrative tooling; never embed it in the frontend. Deletion
  returns 503 when unconfigured and 401 for absent or incorrect credentials.
  This protects an admin operation; individual user accounts/ownership are not implemented yet.
- Article requests allow only public HTTP/HTTPS addresses on ports 80/443, validate
  each redirect, and connect to the validated IP with TLS hostname verification.
  Downloads have connect/read timeouts, a size limit, and a bounded redirect count.
- Blocking summarization, embedding and upload calls run in a thread pool.
  OpenAI uses a 30-second timeout and at most one retry; uploads have a 30-second timeout.
- Failed summaries return errors instead of being stored as content. Unsupported
  uploads are rejected before processing. Supported documents are PDF, DOCX and TXT;
  supported images are PNG, JPEG, WEBP and GIF. Uploads are limited to 10 MB.
- Temporary files are cleaned up on both success and failure. Cloudinary uploads
  begin only after summarization and embedding succeed.
- Questions can be typed without microphone access. Voice users can stop recording,
  review the transcript and select Ask Buddy. Failed questions remain available to retry.
  Voice input uses the browser's Web Speech service, not the project's OpenAI key.
  A Chromium-based browser may expose the API without a working recognition service.
  Permission, microphone, network and unsupported-service failures have distinct
  recovery messages. Recording waits for the browser's start event, ends after one
  utterance or one minute, preserves the typed draft, and never submits automatically.
  If a browser cannot provide speech recognition, use a supported browser or type;
  this app does not currently upload audio to its own transcription endpoint.

Changing credentials does not migrate existing media. The original Cloudinary
account owner must still rotate the credentials exposed in repository history.
Deploying this version requires your own services; no changes here update the original site.

### Tests without accounts or API keys

From `backend`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-test.txt
python -m pytest -q
```

These tests exercise the FastAPI routes with mocked database, AI, storage and
embedding dependencies. They block network access and do not download an embedding
model. Install `requirements.txt` instead when running the actual backend.

From `frontend`:

```bash
npm ci
npm test
npm run lint
npm run typecheck
npm run build
```

Frontend tests mock the API and cover typing, duplicate submission prevention,
unavailable speech APIs, demo questions and their supporting passages, disabled
live configuration, upload retries, partial search results and usage-limit errors. Live MongoDB
vector search, OpenAI responses and Cloudinary uploads still require your own
configured services and a separate integration check.

### Frontend structure

The application pages and shared components use React with TypeScript (`.tsx`).
Tailwind CSS 4 is integrated through Vite; `src/styles/index.css` contains shared
colors, layouts and component styles. `AppShell` provides navigation across the
home, demo, live questions and submission flows. URL parameters preserve the
selected demo lesson, question and asking mode across browser navigation.

The blue gradient, Poppins typography, pill buttons and Buddy mascot are shared
across pages. The homepage keeps its typewriter greeting. Motion respects
`prefers-reduced-motion`. Dark mode, the dismissible three-step tour and sample
lesson progress are saved only in this browser. The header's speaker control
opts into a quiet completion chime; sound and spoken answers both default off.
Sample progress records viewed answers, not a measured learning score.

Live questions request `text/event-stream` from the existing `/api/search`
endpoint. It sends retrieved sources first, actual provider text deltas next,
and an explicit completion event. Limits and retrieval still run before AI
work. Interrupted answers are not marked complete; their retrieved sources
remain available. Requests without the streaming Accept header retain the
JSON API used by evaluation scripts. Navigation cancels the browser request,
and server cancellation closes the provider stream. Citation chips open the
specific answer's source snapshot in a keyboard-accessible side panel.

`npm run build` runs strict TypeScript checks before bundling. Existing JavaScript
helpers and test files remain supported with `allowJs`; they can be migrated
individually. Use typed props and the API shapes in `src/lib/types.ts` for new
components. TypeScript improves development checks; backend validation still
protects incoming requests. The Python backend and deployment paths are unchanged.

## API Endpoint

### Repeatable AI evaluation

Run `python -m scripts.evaluate --output /tmp/buddy-evaluation.json` from
`backend` for the fixed 30-question retrieval baseline without an API key.
See [evaluation instructions](evaluation.md) for embedding comparisons,
opt-in paid answer checks, citation review, latency and token-based cost estimates.
CI saves the baseline report as an artifact. This small fixture does not replace
live Atlas or ingestion testing.

**POST** `/search`

**Request Example:**

```json
{
  "query": "Explain the concept of limits in calculus"
}
```

**Response Example:**

```json
{
  "summary": "A limit in calculus describes the value a function approaches as its input approaches some point. Limits form the foundational basis for defining continuity, derivatives, and integrals. They help mathematicians understand function behavior near specific points, even if the function isn't explicitly defined there. Limits are essential in evaluating instantaneous rates of change and the area under curves. Understanding limits is crucial for applications in physics, engineering, economics, and many other fields.",
  "results": [
    {
      "title": "Limits and Continuity",
      "summary": "Detailed explanation of calculus concepts like limits and continuity.",
      "media_link": "https://example.com/limits",
      "media_type": "video",
      "course": "CALC101",
      "score": 0.93
    }
  ]
}
```

