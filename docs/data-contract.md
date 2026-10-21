# PerClip Data Contract

This document proposes a unified clip metadata contract shared by Android, WeChat bot, server ingest, RAGFlow, RAGGraph, and publishing plugins.

The current implementation uses multipart form fields for `/api/mobile-clips`. This contract should be introduced as a normalized server-side model first, then exposed as a versioned client contract after compatibility is protected.

## Stage 16 Recall compatibility addendum

Stage 16 adds a separate, safe read-and-recall surface documented in
`docs/recall-data-contract.md`. It reads normalized clip metadata, completed
enrichment, routing and knowledge-base display data, but does **not** change
the `/api/mobile-clips` multipart contract or its legacy response.

- Recall owns only `recall_sessions`, `recall_session_items`, and
  `recall_events`; it does not put active sessions, raw fallback text, or graph
  data into `perclip.clip.v1` metadata.
- Candidate content uses completed enrichment first, then credential-redacted
  raw fields. Recall responses and snapshots exclude paths, dataset/document
  IDs, credentials, cookies and authorization material.
- Recall is independent of RAGFlow sync. It makes no RAGFlow/RAGGraph query or
  mutation, and Android Recall models contain no RAGFlow API key.
- Stable topics and graph edges are derived at read time; there is no
  user-managed topic table. Stage 17 owns Android graph layout and animation.

## Goals

- Give every clip one stable identity and provenance record.
- Allow Android and WeChat bot to submit different source details without fragmenting downstream storage.
- Keep binary payloads, raw text, extracted text, archive paths, RAGFlow document IDs, graph IDs, and publishing outputs connected.
- Preserve the current security boundary: clients send only mobile-ingest-authorized content; server-side systems keep RAGFlow, ASR, NAS, and plugin credentials.
- Make future plugins consume a stable contract instead of Android-specific fields.

## Non-Goals

- This contract does not require Android to know RAGFlow API keys, ASR keys, NAS paths, graph internals, or publishing credentials.
- This contract does not turn PerClip into a hosted public cloud relay.
- This contract does not require all clients to upload JSON-only payloads; multipart upload remains valid for binary assets.

## Versioning

Recommended envelope:

```json
{
  "contract_version": "perclip.clip.v1",
  "clip": {},
  "assets": [],
  "processing": {},
  "routing": {},
  "enrichment": {},
  "security": {}
}
```

Rules:

- `contract_version` is required.
- Minor-compatible additions should use optional fields.
- Breaking changes require a new version string.
- Server stores the normalized contract even when the inbound request used legacy multipart fields.

## Core Clip Fields

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `clip_id` | string | yes | source client | Stable client-generated ID for UI and queue tracking. |
| `client_request_id` | string | yes | source client | Idempotency key for server ingest. Current Android already uses this. |
| `source_type` | enum | yes | source client | `text`, `url`, `image`, `file`, `audio`, `screen_clip`, `wechat_message`, `mixed`. |
| `title_hint` | string | no | source client | Human-readable title candidate. |
| `note` | string | no | source client | User note or caption. |
| `text` | string | no | source client | Raw text submitted by the client. |
| `url` | string | no | source client | Canonical source URL when known. |
| `captured_at` | RFC3339 string | yes | source client/server | Client time if trusted enough; server may add received time. |
| `language_hint` | string | no | source client/server | BCP-47-like hint such as `zh-CN` or `en`. |
| `tags_hint` | string array | no | source client/plugin | Optional user or adapter hints. |

## Provenance Fields

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `launcher_type` | enum | yes | source adapter | `android`, `wechat_bot`, `api`, `import`, `plugin`. |
| `launcher_id` | string | no | source adapter | Device name, bot ID, or import job ID. |
| `source_app` | string | no | source adapter | Android app label/package or WeChat context. |
| `source_account_hint` | string | no | source adapter | Redacted display hint only, never a password/token. |
| `source_message_id` | string | no | source adapter | WeChat message ID, platform event ID, or equivalent. |
| `source_url` | string | no | source adapter | Original shared URL before canonicalization. |
| `capture_method` | enum | yes | source adapter | `share_sheet`, `quick_note`, `notification`, `quick_settings`, `accessibility`, `wechat_forward`, `manual_import`, `api`. |

## Asset Fields

Each clip can have zero or more assets.

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `asset_id` | string | yes | source/server | Stable within the clip. |
| `role` | enum | yes | source/server | `original`, `attachment`, `screenshot`, `audio`, `thumbnail`, `extracted_text`, `markdown`, `publish_preview`. |
| `filename` | string | no | source/server | Sanitized before storage. |
| `mime_type` | string | no | source/server | Normalized lowercase MIME type. |
| `size_bytes` | integer | no | source/server | Size of the submitted or derived asset. |
| `content_hash` | string | no | server | Hash of stored bytes or text content. |
| `storage_uri` | string | no | server | User-owned NAS/local path or internal URI. Not required from Android. |
| `text` | string | no | source/server | Inline asset text when no binary payload exists. |
| `source_part_index` | integer | no | source | Multi-file ordering. |

## Processing Fields

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `received_at` | RFC3339 string | yes | server | Server receive time. |
| `archive_status` | enum | yes | server | `received`, `local`, `clip_to_ragflow`, `archive_failed`. Current server already returns related values. |
| `original_path` | string | no | server | PersonalClips or local fallback path. |
| `ragflow_document_id` | string | no | server/RAGFlow | RAGFlow document ID when created. |
| `extraction_status` | enum | no | server/plugin | `not_started`, `completed`, `partial`, `failed`. |
| `graph_status` | enum | no | RAGGraph | `not_started`, `queued`, `completed`, `failed`. |
| `publish_status` | enum | no | publishing plugin | `not_started`, `draft`, `approved`, `published`, `failed`. |
| `error_code` | string | no | server/plugin | Stable machine-readable failure code. |
| `error_message` | string | no | server/plugin | Redacted human-readable error message. |

## Routing Fields

Stage 9 adds an optional top-level `routing` section to `perclip.clip.v1`.
The section is written by the PerClip server from the route decision used by
`/api/mobile-clips`; Android does not submit RAGFlow dataset IDs or server-side
credentials.

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `routing.knowledge_base_id` | string | no | server | Final PerClip Knowledge Base ID. |
| `routing.knowledge_base_name` | string | no | server | Display snapshot only; not the source of truth. |
| `routing.ragflow_dataset_id` | string | no | server | Snapshot of the mapped dataset ID; may be empty. |
| `routing.decision_type` | string | no | server | `manual`, `rule`, `default`, `fallback`, or `error`. |
| `routing.matched_rule_ids` | string array | no | server | All rules matched during preview/ingest routing. |
| `routing.reason` | string | no | server | Human-readable explanation, without secrets. |
| `routing.manual_override` | boolean | no | server | True when Android selected a target Knowledge Base. |
| `routing.routed_at` | RFC3339 string | no | server | Route decision creation time. |
| `routing.previous_knowledge_base_id` | string | no | server | Stage 10 move lineage source Knowledge Base snapshot. |
| `routing.reindex_status` | string | no | server | Stage 10 move/re-route status such as `required`, `queued`, `completed`, or `failed`. |
| `routing.lineage_id` | string | no | server | Stable lineage ID joining route decisions across moves. |

Compatibility rules:

- `routing` is optional so old metadata without this section remains valid.
- New Stage 9 `/api/mobile-clips` metadata includes `routing` when route
  decision persistence succeeds.
- Stage 10 `/api/clips/{clip_id}/move` updates the same `routing` section after
  appending a new route decision, preserving existing `clip`, `provenance`,
  `assets`, `processing`, and `security` sections.
- `ragflow_dataset_id` is a server-side mapping snapshot and may be empty.
- Move metadata does not modify `processing.original_path`,
  `processing.ragflow_document_id`, or `processing.archive_status`.
- The section must not contain mobile ingest tokens, RAGFlow API keys, ASR keys,
  NAS passwords, SSH passwords, cloud account keys, or social-platform
  credentials.

## Enrichment Fields

Stage 11 adds an optional top-level `enrichment` section to `perclip.clip.v1`.
The section is generated by the PerClip server after a clip has been stored and
routed. Old metadata without this section remains valid.

Stage 11 introduced the deterministic `deterministic.v1` engine. The current
projection-backed pipeline writes `deterministic.v7`; direct legacy enrichment
without an extraction projection remains `deterministic.v2`. Both are local and
replayable. They do not call
OpenAI, Gemini, Claude, local models, OCR, ASR, RAGGraph, or RAGFlow document
metadata APIs.

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `enrichment.engine` | string | no | server | Current projected pipeline writes `deterministic.v7`; legacy records retain their original version. |
| `enrichment.status` | enum | no | server | `pending`, `running`, `completed`, `failed`, or `skipped`. |
| `enrichment.title` | string | no | server | Deterministic title candidate from title hint, filename, URL domain, or fallback. |
| `enrichment.summary` | string | no | server | Short deterministic summary, capped from extracted text or file/URL hints. |
| `enrichment.tags` | string array | no | server | In `deterministic.v7`, up to two source-grounded terms from the highest-scoring fixed topic. Legacy engines may contain transport, routing, or MIME-derived tags. |
| `enrichment.key_points` | string array | no | server | In projection-backed `deterministic.v6+`, up to three ordered, redacted source sentences capped at 240 characters each; insufficient content and legacy no-projection v2 yield `[]`. |
| `enrichment.language` | string | no | server | Simple heuristic such as `zh-CN`, `en`, or empty string. |
| `enrichment.extracted_text` | string | no | server | Text/url/note merge or a filename-based placeholder for file-like inputs. |
| `enrichment.updated_at` | RFC3339 string | no | server | Last enrichment write time. |
| `enrichment.error_code` | string | no | server | Stable redacted failure code when enrichment fails. |
| `enrichment.error_message` | string | no | server | Redacted failure message when enrichment fails. |

Compatibility rules:

- `enrichment` is optional so old metadata remains valid.
- Enrichment updates must preserve `clip`, `provenance`, `assets`,
  `processing`, `security`, and `routing`.
- Enrichment must not modify `processing.original_path`,
  `processing.ragflow_document_id`, or `processing.archive_status`.
- Enrichment must not change `/api/mobile-clips` legacy response fields.
- `deterministic.v7` applies only when a cleaned extraction projection is
  available. The no-projection `deterministic.v2` path remains byte-for-byte
  compatible in tag derivation.
- `deterministic.v7` tags must occur in the projected title or body, use title-
  weighted fixed-topic evidence, remain limited to two terms, and must not
  promote transport, storage, routing, MIME, or arbitrary fixed-length text
  slices into user-visible concepts.
- projection-backed key points must be copied from the redacted projected body,
  preserve source order, and remain an additive array in normalized metadata,
  enrichment responses, and the active-content quality read model.
- The section must not contain mobile ingest tokens, RAGFlow API keys, ASR keys,
  NAS passwords, SSH passwords, cloud account keys, social-platform credentials,
  cookies, authorization headers, or credential-like source strings.

## RAGFlow Sync Fields

Stage 12 adds an optional top-level `ragflow_sync` section to `perclip.clip.v1`.
The section records a server-side dry-run sync plan only. Stage 12 does not call
real RAGFlow HTTP APIs, upload documents, update `meta_fields`, disable/delete
documents, or move documents across datasets.

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `ragflow_sync.operation` | enum | no | server | `upload_document`, `update_meta_fields`, `reindex_after_move`, `skip_no_dataset`, or `skip_no_enrichment`. |
| `ragflow_sync.status` | enum | no | server | `planned`, `skipped`, `blocked`, or `failed`. |
| `ragflow_sync.dry_run` | boolean | no | server | Stage 12 always writes `true`. |
| `ragflow_sync.remote_document_changed` | boolean | no | server | Stage 12 always writes `false`. |
| `ragflow_sync.ragflow_dataset_id` | string | no | server | Snapshot from the latest route decision. |
| `ragflow_sync.ragflow_document_id` | string | no | server | Snapshot from stored clip processing state. |
| `ragflow_sync.reason` | string | no | server | Redacted explanation for the selected operation/status. |
| `ragflow_sync.plan` | object | no | server | JSON object containing dry-run plan details such as target dataset, existing document ID, title, summary, tags, language, and meta fields. |
| `ragflow_sync.updated_at` | RFC3339 string | no | server | Last sync plan write time. |

Compatibility rules:

- `ragflow_sync` is optional so old metadata remains valid.
- Sync updates must preserve `clip`, `provenance`, `assets`, `processing`,
  `security`, `routing`, and `enrichment`.
- Sync updates must not modify `processing.original_path`,
  `processing.ragflow_document_id`, or `processing.archive_status`.
- `ragflow_sync.plan` must be a JSON object.
- `dry_run` must remain true and `remote_document_changed` must remain false in
  Stage 12.
- The section must not contain mobile ingest tokens, RAGFlow API keys, ASR keys,
  NAS passwords, SSH passwords, cloud account keys, social-platform credentials,
  cookies, authorization headers, or credential-like plan fields.

## RAGFlow API Verification

Stage 14A adds a server-only read probe for checking whether the configured
RAGFlow service is reachable. This probe is not part of `perclip.clip.v1`
metadata and does not write clip metadata, sync jobs, or a probe result table.

Endpoint:

- `GET /api/ragflow/probe`

Response shape:

```json
{
  "ok": true,
  "ragflow": {
    "configured": true,
    "status": "reachable",
    "base_url": "https://ragflow.example",
    "capabilities": {
      "dataset_list": true,
      "dataset_create": false,
      "document_upload": false,
      "document_meta_fields": false,
      "document_delete": false,
      "cross_dataset_move": false
    },
    "warnings": [],
    "checked_at": "2026-07-10T00:00:00+00:00",
    "latency_ms": 123,
    "response_shape": "dict_with_data",
    "http_status": 200
  }
}
```

Compatibility rules:

- When RAGFlow is not configured, the endpoint returns `ok=true`,
  `configured=false`, and `status=disabled`.
- The probe may attempt read-only dataset-list endpoint variants, but all
  mutation capability flags remain `false` in Stage 14A.
- The response exposes only a sanitized base URL, status, response shape,
  latency, and capability flags.
- The probe does not change `/api/mobile-clips` legacy responses.

## Security Fields

These fields describe authorization context without storing secrets.

| Field | Type | Required | Owner | Notes |
| --- | --- | --- | --- | --- |
| `auth_context` | object | yes | server | Records that mobile ingest token was used, without storing the token. |
| `token_id` | string | no | server | Optional hash or label for token rotation/audit. |
| `redaction_level` | enum | yes | server | `none`, `metadata_only`, `content_redacted`. |
| `credential_scope` | string array | no | plugin/server | Names of server-side capabilities used, not secret values. |

Example:

```json
{
  "auth_context": {
    "method": "mobile_ingest_token",
    "token_id": "mobile-token-2026-q3",
    "verified": true
  },
  "redaction_level": "metadata_only",
  "credential_scope": ["ragflow:personalclips", "asr:baidu"]
}
```

## Example Normalized Clip

```json
{
  "contract_version": "perclip.clip.v1",
  "clip": {
    "clip_id": "android-9f5b",
    "client_request_id": "android-9f5b:demo.pdf",
    "source_type": "file",
    "title_hint": "demo.pdf",
    "note": "Read later",
    "text": "",
    "url": "",
    "captured_at": "2026-07-09T10:00:00Z",
    "language_hint": "zh-CN",
    "tags_hint": []
  },
  "provenance": {
    "launcher_type": "android",
    "launcher_id": "OPPO Find X PerClip",
    "source_app": "Files",
    "source_account_hint": "",
    "source_message_id": "",
    "source_url": "",
    "capture_method": "share_sheet"
  },
  "assets": [
    {
      "asset_id": "original-1",
      "role": "original",
      "filename": "demo.pdf",
      "mime_type": "application/pdf",
      "size_bytes": 123456,
      "content_hash": "",
      "storage_uri": "",
      "text": "",
      "source_part_index": 0
    }
  ],
  "processing": {
    "received_at": "",
    "archive_status": "received",
    "original_path": "",
    "ragflow_document_id": "",
    "extraction_status": "not_started",
    "graph_status": "not_started",
    "publish_status": "not_started"
  },
  "security": {
    "auth_context": {
      "method": "mobile_ingest_token",
      "token_id": "",
      "verified": true
    },
    "redaction_level": "metadata_only",
    "credential_scope": []
  }
}
```

## Current Android Multipart Mapping

| Current field | Contract target |
| --- | --- |
| `source_type` | `clip.source_type` |
| `title_hint` | `clip.title_hint` |
| `note` | `clip.note` |
| `text` | `clip.text` or `assets[].text` |
| `url` | `clip.url` and possibly `provenance.source_url` |
| `mime_type` | `assets[].mime_type` |
| `device_name` | `provenance.launcher_id` |
| `source_app` | `provenance.source_app` |
| `captured_at` | `clip.captured_at` |
| `client_request_id` | `clip.client_request_id` |
| multipart `file` | `assets[]` with `role=original` or `attachment` |

## WeChat Bot Mapping

| WeChat source | Contract target |
| --- | --- |
| message ID | `clip.client_request_id` and `provenance.source_message_id` |
| sender/group display | `provenance.source_account_hint` |
| forwarded text | `clip.text` |
| forwarded URL | `clip.url` and `provenance.source_url` |
| image/file/audio | `assets[]` |
| bot instance | `provenance.launcher_type=wechat_bot`, `launcher_id=<bot id>` |

The bot must not put WeChat login secrets, cookies, or account passwords into clip metadata.

## RAGFlow Mapping

RAGFlow should receive user-owned archive paths, title, extracted text, and document assets from the server side.

Recommended mapping:

- `clip.title_hint` or server title -> RAGFlow document title.
- `assets[role=original]` and derived markdown/text -> RAGFlow document payload.
- `processing.ragflow_document_id` <- RAGFlow response.
- `provenance` and selected metadata -> document metadata, after redaction.

Android must never send or store the RAGFlow API key.

## RAGGraph Mapping

RAGGraph should consume normalized server-side events:

- `clip_id`;
- stable archive path;
- extracted text path;
- source URL;
- source app/account hints;
- timestamps;
- derived entities, topics, and relationships.

Graph construction should be server/plugin-side so mobile clients remain simple and credential-free.

## Publishing Plugin Mapping

Publishing plugins should consume:

- normalized clip metadata;
- user-selected original or derived assets;
- extracted summaries and tags;
- provenance links;
- explicit user approval state.

Publishing plugins must declare:

- required credentials;
- target platform;
- content read scope;
- write/post scope;
- logging behavior;
- preview/dry-run support;
- manual approval requirement.

The plugin should store platform credentials only in the user-owned server/plugin environment, not in Android.

## Migration Plan

1. Add server-side normalized metadata storage derived from current multipart fields.
2. Add contract validation tests for Android-compatible payloads.
3. Add WeChat bot adapter mapping to the same normalized contract.
4. Add downstream exporter events for RAGFlow/RAGGraph/plugins.
5. Only after compatibility is proven, consider a versioned JSON metadata part in Android multipart uploads.
# Stage 15 sync reliability

`ragflow_sync` metadata may report `planned`, `running`, `completed`, `failed`,
`blocked`, or `skipped`. It contains only operation, status, dry-run state,
dataset/document identifiers, a sanitized plan, and sanitized failure details.
It must never contain authorization headers, API keys, tokens, cookies, NAS, or
SSH credentials. `/api/mobile-clips` legacy response fields are unchanged.
Guarded pending sync uses only current local snapshots and accepts no
caller-supplied dataset or document IDs. It remains subject to the same
explicit real-sync and dataset allowlist gates; dataset mutation, document
delete/disable, cross-dataset movement, and reindex remain disabled.

## Stage 20 ingest contract

All ingress maps to `perclip.ingest.v1` commands and one canonical ingest
service. `clips` and PersonalClips remain the sole clip source of truth;
`ingest_receipts` is only a safe idempotency/status index. Mobile uses
`legacy_mobile`; versioned adapters use `strict_v1` and cannot reuse an
unverifiable legacy ID. Receipts store no payload, path, credential, or remote
dataset/document identifier.
