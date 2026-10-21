# Ingest API v1

Strict JSON and multipart envelopes require a timezone-aware `captured_at` and a valid IANA `captured_timezone`; capture time is stored and signed in canonical UTC form. Both v1 endpoints enforce the configured total request size from actual body bytes before JSON or multipart parsing, in addition to the multipart file-size limit. Oversize requests return a fixed 413 response.

Canonical v1 results and receipt responses never contain RAGFlow dataset/document IDs or storage paths. The legacy mobile response retains its historical `ragflow_document_id` key through a separate compatibility projection.

All v1 endpoints use the existing Bearer mobile ingest token and strict replay semantics. The contract version is exactly `perclip.ingest.v1`. Unknown fields, excessive depth or size, invalid identifiers, unsafe secret-like source/account hints, empty content, timestamps without an offset, and invalid IANA `captured_timezone` values are rejected. Accepted timestamps are normalized to a canonical UTC ISO-8601 representation before signature generation.

## JSON clips

`POST /api/ingest/v1/clips` accepts `application/json` for non-binary `text` and `url` clips only.

```json
{
  "contract_version": "perclip.ingest.v1",
  "client_request_id": "wechat:message:123",
  "source": {
    "adapter": "wechat_bot",
    "client_id": "bot-main",
    "event_id": "message-123",
    "source_app": "WeChat",
    "account_hint": ""
  },
  "clip": {
    "source_type": "text",
    "title_hint": "",
    "note": "",
    "text": "example",
    "url": "",
    "mime_type": "text/plain",
    "captured_at": "2026-07-12T10:00:00+08:00",
    "captured_timezone": "Asia/Shanghai",
    "device_name": ""
  },
  "capture": {
    "client_batch_id": "",
    "parent_client_request_id": "",
    "part_index": 0,
    "part_count": 1,
    "part_role": "text",
    "source_intent": "share",
    "content_fingerprint": ""
  },
  "routing": {"target_knowledge_base_id": ""}
}
```

JSON requests reject `file` and `image`, base64 strings, and data URLs. They do not accept server paths or embedded assets.

## Multipart clips

`POST /api/ingest/v1/clips/multipart` accepts `multipart/form-data` with exactly one `envelope_json` field and one `file` part. The envelope uses the same v1 schema; source types are `image`, `file`, and `screen_clip`.

One request represents one zero-based capture part and one asset. Multiple file parts, a missing file, disallowed MIME types, oversized requests/files, server-path fields, base64, and data URLs are rejected. Filenames are reduced to their basename. The asset SHA-256 participates in the strict signature, so replaying the same request ID with changed bytes returns 409.

## Success and replay

A successful response is a safe result projection containing stable identifiers and status, including `receipt_id`, `clip_id`, `client_request_id`, `status`, `archive_status`, `metadata_status`, `duplicate`, and safe capture/routing summaries. An exact replay returns the same `clip_id` and `receipt_id` with `duplicate=true`.

The response never contains raw text or file bytes, base64, `original_path`, `storage_uri`, credentials, Authorization headers, or RAGFlow dataset/document IDs.

## Receipt lookup

`GET /api/ingest/v1/receipts/{receipt_id}` returns a safe allowlisted status plus capture and routing summaries. Receipts have `processing`, `received`, or `failed` status and are not clip content records. Failed receipts expose only a stable category such as `archive_error`; they never expose an exception or upstream body. An exact retry of a failed strict receipt reuses that receipt and returns a stable conflict without archiving or creating a clip again. Unknown receipts return 404; authentication is required.

## Errors

| Status | Meaning |
| --- | --- |
| 401 | Missing or invalid ingest token |
| 409 | Request ID/signature conflict or capture ownership conflict |
| 413 | Request or file exceeds its configured bound |
| 415 | Unsupported media type |
| 422 | Invalid schema, field, capture identity, timestamp, or payload |
| 502 | Archive operation failed |

Error `detail` values are stable and safe. They do not echo user content or expose paths, SQL, tracebacks, upstream bodies, secrets, or infrastructure identifiers.
