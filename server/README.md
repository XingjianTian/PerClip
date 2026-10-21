# PerClip Server

PerClip Server is the single data and processing control plane for Android,
LangBot, imports, and future connectors. It is a modular monolith deployed as:

- `perclip-api`: FastAPI authentication, contract validation, idempotency,
  durable acceptance, product queries, Knowledge, and Recall;
- `perclip-worker`: persistent archive/extract/clean/enrich/classify-topic/route/index jobs.

PersonalClips is the asset source of truth. RAGFlow is a replaceable,
rebuildable index and is not required for Recall.

## Production mode

`Settings.from_env()` defaults to `PERCLIP_PROCESSING_MODE=worker`. Strict v1
ingest returns HTTP 202 after the clip, source event, staged asset, route intent,
receipt, immutable public identity, and first durable job have been recorded.
It does not fetch a URL, OCR, summarize, or call RAGFlow in the request.

Start the two processes from the repository root with the private `.env`:

```bash
make api
# In another terminal:
make worker
```

The Worker uses SQLite WAL, tokenized leases with an active heartbeat, bounded
retry, versioned stage lineage, and an atomic complete-and-enqueue transition.
It claims only the next job it is about to execute; `--once --limit N`
processes at most `N` jobs without pre-leasing the rest of the queue.

## Authentication

`PERCLIP_INGEST_TOKEN` is the Android/admin credential. Optional
`PERCLIP_CONNECTOR_TOKENS_JSON` maps non-Android adapters to independent
ingest-only tokens, for example `wechat_bot`. Once any connector mapping is
configured, a non-Android adapter without its own mapping is rejected.
Connector tokens cannot query or mutate Knowledge, Recall, Settings, or admin
surfaces.

No client receives NAS, RAGFlow, OCR, ASR, or LLM credentials.

## URL and file processing

The Worker includes:

- fixed-public-IP HTTP/HTTPS fetching with per-redirect validation;
- private, loopback, link-local, reserved, and cloud-metadata address blocking;
- URL userinfo rejection, MIME/size/time/redirect budgets, and canonical URL
  tracking-parameter cleanup;
- versioned readable HTML/plain-text extraction with quality status;
- text, DOCX, XLSX, PPTX, PDF, RTF, and legacy fallback extraction;
- deterministic boilerplate, legal-tail, and duplicate-line cleaning.

Raw/staged assets and versioned derivatives are stored separately. A weak
extraction remains partial and preserves the original; it is never presented
as a successful high-quality extraction.

The latest non-empty `clean_markdown`/`extracted_text` asset is the canonical
enrichment input projection. Web title, resolved/canonical URL, quality score,
and partial/completed state are persisted with the asset and copied into safe
normalized metadata. Enrichment, Knowledge status, routing, and Recall consume
that projection. A terminal extractor failure retains its failed run and safe
error, then continues from a raw-content fallback so the accepted memory does
not disappear.

## RAGFlow safety

Real mutations require all of:

- `RAGFLOW_MODE=index` (`off` is the environment default; `qa` is
  capability-only);
- configured server-side endpoint and key;
- `PERCLIP_ENABLE_REAL_RAGFLOW_SYNC=1`;
- an explicit Dataset allowlist;
- a final route decision and completed clean/enrichment stages.

Off and qa modes make no index HTTP call. Index mode without the mutation
gates records a dry-run index reference. Core becomes ready after route;
RAGFlow failure does not delete the accepted or archived clip or block
Knowledge/Recall.

RAGFlow v0.26.1's public Chunk API is not vector evidence. A deployment that
needs verified activation must start
`tools/run_operator_verified_worker.py` and configure its exact-allowlisted
command transport. The NAS container deployment uses a root-owned host proxy
and a mode-0600 Unix socket: the proxy alone may issue the fixed read-only
verifier command, while the Worker container receives no Docker socket. The
operator Dataset ID must exactly equal the sole real-sync allowlist entry.

## Guarded pipeline controls

Terminal jobs are not silently reopened, and a dry-run `planned` index is not
treated as proof of a real upload. Operators can use the internal CLI after
fixing configuration:

```bash
python -m perclip_ingest.pipeline_control retry-failed \
  --job-id JOB_ID \
  --request-id UNIQUE_OPERATOR_REQUEST_ID \
  --confirm RETRY_FAILED_PIPELINE_JOB

python -m perclip_ingest.pipeline_control promote-real-sync \
  --clip-id CLIP_ID \
  --request-id UNIQUE_OPERATOR_REQUEST_ID \
  --confirm PROMOTE_PLANNED_RAGFLOW_REAL_SYNC
```

The promotion command refuses to schedule unless every real-sync environment
gate is enabled. Each request ID is idempotent. `pipeline_control_events`
retains the old terminal status, attempt count, and safe error before a retry;
neither operation overwrites a running lease. The CLI changes only local
control-plane state. A promoted job can mutate RAGFlow only when the separately
started Worker has the complete real-sync configuration and Dataset allowlist.

## Legacy compatibility and migration

The dynamic ClipToRAGFlow adapter remains only in `inline` rollback mode.
Worker mode rejects it at configuration validation, so the old archiver cannot
silently dual-write with the unified pipeline.

`python -m perclip_ingest.legacy_migration` audits the legacy SQLite database
read-only by default. Apply mode requires an exact confirmation, Dataset
mapping, and a destination backup. It never modifies the legacy database or
RAGFlow and is idempotent through `legacy_import_map`.

`python -m perclip_ingest.pipeline_audit --data-dir ...` performs a separate
read-only consistency audit of canonical identities, source events, assets,
Knowledge Base associations, jobs, and index references.

See the root `.env.example` and `docs/ENVIRONMENT.md`, `deploy/nas-systemd.md`, and the API/contracts under
`docs/` for configuration and operations.
