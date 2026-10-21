# Multipart Capture Policy

One Android `ACTION_SEND_MULTIPLE` intent creates one local batch and one
independent upload request per item. For a local parent `abc`, three files use:

```text
client_batch_id=abc
parent_client_request_id=abc:
abc:0:report.pdf
abc:1:image.png
abc:2:notes.txt
```

Filenames in request ids are basename-only, ASCII-safe, and bounded. The index
is zero-based so a retry generates exactly the same part id.

Parts may succeed, fail, arrive out of order, and retry independently. The
Android queue persists every `UploadPart`; a retry skips parts already marked
`Uploaded` and reuses the failed part's original request id. The queue retains
cached payloads until every submitted part succeeds. Each item is copied
independently: a null or unreadable URI remains at its original zero-based index
as a `Failed` part with an empty cached path and safe fixed message, while other
readable parts stay `Waiting` and upload normally. Missing filename/MIME uses
bounded `item` and generic MIME fallbacks. Intents above 100 items fail locally.

Manual retry changes `Uploading` parts back to `Waiting`, preserves `Uploaded`
parts, and restores a failed file/image part only while its cached file remains
usable. Text/URL parts need no file cache. A missing payload remains `Failed`,
cannot enter pending work, and cannot make a zero-attempt worker report success.
The worker derives the overall state from all persisted parts and deletes all
cached payloads only when every part is `Uploaded`.

The server records bounded per-batch attempts and reports these states:

- `empty`: no part attempt exists;
- `partial`: at least one part is processing/received and parts are missing;
- `failed`: at least one missing part's latest attempt failed;
- `completed`: all zero-based indices in `0..part_count-1` have stored clips.

A duplicate replay does not increase `received_count`. A successful retry
replaces the part's failed attempt state with received and can move the batch
from `failed` to `completed`. Cross-part parent id, count, index ownership, and
request id are validated under a per-batch lock. Queries use indexed batch
columns/attempt rows and do not scan historical clips or create placeholders.
The local detail resolver may map any part id back to its persisted parent.
When a local part is unreadable, the server has no row for it: server batch
status can therefore remain `partial` while Android reports the local part as
`Failed`.

`GET /api/mobile-clips/{clip_id}/capture` exposes only safe capture, routing,
enrichment, and RAGFlow-sync statuses. It does not initiate enrichment, AI,
RAGFlow, or RAGGraph work.

Known limitations: Stage 19 does not provide a batch cancel operation or a
metadata-repair endpoint. Emulator `ACTION_SEND_MULTIPLE` and physical-device
share-sheet behavior remain release-candidate verification work.

Stage 20 adds `/api/ingest/v1/clips/multipart`: exactly one envelope and asset,
the same ownership/attempt machinery, basename filename handling, existing
MIME/size limits, and asset SHA-256 in strict replay. Base64, data URLs, server
paths, and multiple-file requests are rejected.
