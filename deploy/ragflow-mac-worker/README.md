# Optional RAGFlow worker durability patch

This standalone patch is separate from the PerClip API/Android application.
The pinned upstream Docker image and exact source checks support reproducible
patch application. Run the offline Python test file to validate pending-message,
terminal-state and transaction behavior. Production deployments need their own
private configuration and validation; no historical operator test results or
private dataset identities are included here. Graph/RAPTOR/Canvas/Memory/TOC and
distributed exactly-once guarantees are outside its scope.

## Isolated tests

Build the pinned optional image with `python3 deploy/ragflow-mac-worker/build.py`.
Run its tests inside that candidate image, not in the PerClip Server environment:

```sh
docker run --rm --network none --entrypoint python3 \
  -v "$PWD/deploy/ragflow-mac-worker/test_worker_patch.py:/tmp/test_worker_patch.py:ro" \
  perclip/ragflow-mac-worker:20261015-hardening /tmp/test_worker_patch.py
```

Do not mount production data, credentials, Docker sockets or service configuration
for these offline unit tests. The test runner has mocked external dependencies.
