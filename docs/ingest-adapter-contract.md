# Ingest adapter contract

An ingest adapter is a pure mapping boundary between a transport and `IngestCommand`. Supported adapter identities are `android`, `api`, `wechat_bot`, `webhook`, and `import`. Adding an adapter does not add another clip type or persistence path.

## Required mapping

Every adapter produces:

- `contract_version`: `perclip.ingest.v1` for versioned adapters;
- `client_request_id` and a replay policy;
- source identity: adapter, bounded client/event IDs, source application, and a sanitized optional account hint;
- clip fields: source type, hints/content, MIME type, timezone-aware capture time, timezone, and device hint;
- capture identity: batch/parent IDs, zero-based part index, count, role, intent, and optional SHA-256 fingerprint;
- optional routing target;
- at most one in-memory asset with basename filename, allowed MIME type, and bytes.

Mapping functions perform parsing and structural normalization only. They must not archive, write files, call `ClipStore`, select routing rules, create metadata, update capture attempts, or issue receipts.

## Adapter functions

`mobile_form_to_command` maps the existing `/api/mobile-clips` form to a command using adapter `android` and replay policy `legacy_mobile`. It preserves all Stage 19 field defaults and compatibility behavior.

`json_envelope_to_command` maps a bounded v1 JSON object to a `strict_v1` command. It supports only `text` and `url` and rejects unknown fields, binary representations, base64, and data URLs.

`multipart_envelope_to_command` combines a bounded v1 JSON envelope with exactly one uploaded file. It supports `image`, `file`, and `screen_clip`, retains payload bytes only in memory, and supplies the asset hash for strict replay.

## Identity and safety

Transport message/event IDs should be preserved as stable, sanitized source IDs and used to derive a deterministic `client_request_id`; random IDs defeat replay protection. Account/chat hints must be minimized and sanitized, and secret-like values are rejected. Tokens, cookies, Authorization headers, webhook secrets, server paths, dataset/document IDs, and upstream response bodies are not command fields.

Strict adapters must not reuse a legacy request ID without a verifiable strict signature, and legacy requests cannot reuse strict receipts. `captured_at` and `captured_timezone` are required for strict adapters: timestamps are normalized to UTC before signing and the timezone must be a valid IANA zone. The signature covers adapter/client/event IDs, sanitized `source_app` and `device_name`, content hashes, capture identity, routing target, canonical capture time, sanitized asset basename, normalized MIME, and asset bytes. `account_hint` is deliberately excluded because it is neither persisted nor routed. An exact strict replay maps to the same signature; any meaningful mapped-field or asset-byte change maps to a conflict.

## Result projection

Adapters project only the canonical safe result. The legacy mobile adapter may retain its established Stage 19 response shape. Versioned adapters return the v1 receipt shape. No projection may reveal base64/payload bytes, `original_path`, `storage_uri`, credentials, or RAGFlow IDs.
