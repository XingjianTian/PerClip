# Capture Contract

Stage 19 keeps the server clip as the only Recall memory identity. A capture
parent or batch is client-side grouping metadata; neither becomes a server clip
or a new Recall entity.

## Identity

- `client_request_id` is the idempotency key for one server clip (one part).
- A text/URL/single-item capture keeps the compatible request id
  `<local_clip_id>:`. A single file may keep the existing
  `<local_clip_id>:<sanitized_filename>` form.
- `client_batch_id` is the stable local capture id for one multi-item share
  intent. Android currently reuses the persisted local clip UUID. A single
  capture leaves this field empty rather than fabricating a multipart batch.
- `parent_client_request_id` is the stable local parent, normally
  `<local_clip_id>:`; it is never used as a server clip id.
- `client_part_index` is zero-based and `client_part_count` is in `1..100`.
- `part_role` is one of `single`, `file`, `image`, `text`, `url`, or `mixed`.

Each response includes `clip_id`, `client_request_id`, and a safe `capture`
object. Archive paths are intentionally not returned to mobile clients.

The Android queue persists the generated request id and capture metadata before
upload. Retry, process restart, and queue replay therefore reuse the same id;
they do not derive it from a content URI, cache path, server path, or a new UUID.
The queue also freezes `captured_at` and the safe IANA `captured_timezone` once
at enqueue time. Every part and every later retry reuses that provenance rather
than substituting upload time or the device's then-current timezone.

## Safety

The contract never carries Android absolute paths, server paths, access tokens,
cookies, headers, or RAGFlow credentials. `content_fingerprint`, when supplied,
is a SHA-256 hex digest only. Server storage paths remain internal metadata and
are excluded from `/api/mobile-clips`, batch, capture, and Recall responses.
Android ignores `original_path` even if an older server sends it, clears legacy
`remotePath` / `remoteOriginalPath` values while reading queue JSON, and writes
those compatibility fields back only as empty strings.

## Compatibility

All capture form fields are optional. Old clients continue to create a single
part with index `0`, count `1`, role `single`, and intent `unknown`.
An empty batch id is valid only for index `0`, count `1`. A non-empty batch
requires both parent and per-part request ids. A one-part batch remains accepted
only for historical identity attachment; new Android single captures omit it.

`GET /api/mobile-clips/{clip_id}/capture` requires the mobile bearer token and
returns capture identity plus safe routing, enrichment, and sync status only.
Malformed numeric ids return `422`, and unknown ids return `404`. Repair is not
implemented in Stage 19; missing metadata repair remains a later stage.

## Versioned adapters

Stage 20 reuses this zero-based identity in every adapter. JSON and multipart
v1 envelopes map to the same capture model and create no adapter-specific
entity. Strict replay signs capture identity; Android form and legacy replay
remain compatible.
