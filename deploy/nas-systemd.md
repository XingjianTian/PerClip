# PerClip NAS systemd deployment

PerClip production runs as a modular monolith with two processes over the same
metadata database and asset root:

```text
perclip-ingest.service  -> validate, authenticate, durably accept, return 202
perclip-worker.service  -> archive, extract, clean, enrich, route, index
```

The base deployment uses SQLite WAL and one Worker. It does not require Redis,
Celery, Kubernetes, or the legacy ClipToRAGFlow runtime.

## 1. Install files

```bash
sudo mkdir -p /opt/perclip /etc/perclip /srv/personal-clips
sudo rsync -a server/ /opt/perclip/server/
sudo cp deploy/perclip-ingest.service /etc/systemd/system/perclip-ingest.service
sudo cp deploy/perclip-worker.service /etc/systemd/system/perclip-worker.service
sudo cp .env.example /etc/perclip/perclip-ingest.env
```

The examples assume the Python environment is `/opt/perclip/.venv` and both
processes use `/opt/perclip/server` as their working directory.

## 2. Configure server-side secrets

Keep `/etc/perclip/perclip-ingest.env` owned by `root:perclip` with mode `640`
or stricter. Never copy it into Android, Git, screenshots, logs, or handoff
documents.

Required base values:

```text
PERCLIP_INGEST_TOKEN=<Android/admin token>
PERCLIP_CONNECTOR_TOKENS_JSON={"wechat_bot":"<independent connector token>"}
PERCLIP_DATA_DIR=/opt/perclip/server/data
PERCLIP_ASSET_ROOT=/srv/personal-clips
PERCLIP_PROCESSING_MODE=worker
PERCLIP_DEPLOYMENT_ENVIRONMENT=production
PERCLIP_HOST=0.0.0.0
PERCLIP_PORT=18081
PERCLIP_ENABLE_CLIP_TO_RAGFLOW=0
```

The Android/admin token can use product query and management APIs. Connector
tokens are ingest-only and adapter-scoped. A LangBot connector must use the
`wechat_bot` token and must not receive NAS, RAGFlow, OCR, ASR, or LLM secrets.

Optional RAGFlow values remain server-side:

```text
RAGFLOW_BASE_URL=<internal RAGFlow endpoint>
RAGFLOW_API_KEY=<server-side key>
RAGFLOW_MODE=off
PERCLIP_ENABLE_REAL_RAGFLOW_SYNC=0
PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS=<explicit comma-separated allowlist>
```

Keep real sync disabled through migration dry-runs. Enable it only after
Dataset routing and the legacy import map have been reconciled.

## 3. Create runtime user and Python environment

```bash
sudo useradd --system --home /opt/perclip --shell /usr/sbin/nologin perclip || true
sudo chown -R perclip:perclip /opt/perclip /srv/personal-clips
sudo chown root:perclip /etc/perclip/perclip-ingest.env
sudo chmod 640 /etc/perclip/perclip-ingest.env

cd /opt/perclip
sudo -u perclip python3 -m venv .venv
sudo -u perclip .venv/bin/python -m pip install -U pip
sudo -u perclip .venv/bin/python -m pip install -e "server[dev]"
```

## 4. Validate without external writes

Start with RAGFlow sync disabled. Validate configuration without processing queued jobs:

```bash
cd /opt/perclip
# This optional operator command requires uv; systemd loads EnvironmentFile itself.
PERCLIP_ENV_FILE=/etc/perclip/perclip-ingest.env scripts/with_env.sh python -c \
  'from perclip_ingest.config import Settings; Settings.from_env(); print("Configuration valid")'
```

`GET /health` should report `processing_mode: worker` and
`archive_mode: worker`. A strict ingest returns HTTP 202 and a safe receipt;
the Worker then advances its durable stages.

## 5. Enable both services

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now perclip-ingest.service perclip-worker.service
sudo systemctl status perclip-ingest.service perclip-worker.service
```

Use the existing authenticated smoke scripts without printing tokens. Inspect
service logs for safe error codes only; raw content, URLs with private data,
tokens, upstream response bodies, and filesystem paths must not be logged.

## 6. Legacy data migration

The migration command is read-only unless `--apply` is supplied:

```bash
cd /opt/perclip/server
../.venv/bin/python -m perclip_ingest.legacy_migration \
  --legacy-db <legacy-personal-clips.sqlite3> \
  --data-dir "$PERCLIP_DATA_DIR"
```

The report contains counts only. Applying requires all of the following:

- a verified legacy SQLite backup and asset backup;
- a configured legacy Dataset ID available through an environment variable;
- a destination backup directory;
- the exact confirmation phrase documented by `--help`/the migration runbook;
- real RAGFlow sync still disabled.

The importer never writes the legacy SQLite database or RAGFlow. It copies
active records into the canonical data plane, maps inactive/missing records,
and records existing index references for later reconciliation.

Run the read-only destination audit before and after import:

```bash
../.venv/bin/python -m perclip_ingest.pipeline_audit \
  --data-dir "$PERCLIP_DATA_DIR"
```

## 7. Rollback boundary

`PERCLIP_PROCESSING_MODE=inline` exists only for controlled rollback during
migration. Worker mode refuses `PERCLIP_ENABLE_CLIP_TO_RAGFLOW=1`, preventing
the old archiver and the unified pipeline from writing simultaneously. Do not
run the legacy LangBot archiver and the new connector against the same incoming
events.

## 8. Existing-database cutover gate

Do not treat additive schema initialization as proof that an existing database
is ready for the unified read model. Before replacing a legacy synchronous
service, audit every existing Clip for:

- one stable row in `clip_identities`;
- the expected row in `clip_knowledge_bases`;
- no unexpected outbox job or processing run;
- preserved Knowledge, Recall and detail visibility.

If identity or Knowledge Base association rows are missing, stop before the
production write pause. Produce a counts-only dry-run and an idempotent,
transactional minimum backfill plan, then obtain explicit authorization before
implementing or applying it. Schema initialization and Worker startup must not
silently reprocess historical Clips to repair read compatibility.

For the approved Stage 23.3A existing-database backfill, run the dedicated
read-only audit first:

```bash
../.venv/bin/python -m perclip_ingest.existing_data_backfill \
  --data-dir "$PERCLIP_DATA_DIR"
```

Review its counts and retain the exact `review_fingerprint`. Apply is refused
unless it receives that fingerprint, the separate final verified SQLite
backup, and the exact confirmation phrase:

```bash
../.venv/bin/python -m perclip_ingest.existing_data_backfill \
  --data-dir "$PERCLIP_DATA_DIR" \
  --apply \
  --confirm BACKFILL_EXISTING_UNIFIED_READ_MODEL \
  --expect-review-fingerprint "<exact dry-run fingerprint>" \
  --verified-backup "<final verified SQLite backup>"
```

The command inserts only missing `clip_identities` and
`clip_knowledge_bases`. It rejects multiple active Knowledge Bases, existing
processing/index state, Clip drift, backup-content drift, unexpected
associations, database triggers or failed integrity checks. It never creates a
job or calls RAGFlow.

The cutover account must also be able to install the reviewed Worker unit and
manage only the two PerClip services. Writable application or environment
directories are not a substitute for systemd authorization. Never use a
privileged container or host-namespace bypass to work around this gate.

The Stage 23.3A privacy-safe rehearsal and rollback procedure is documented in
`docs/stage23-3a-unified-nas-cutover.md`.

## 9. Containerized runtime fallback

The direct-host units above remain preferred when the NAS provides the
repository-supported Python version. Do not lower `requires-python` or run the
production service on an older interpreter merely because one is already
installed.

When the host has no Python 3.11 or newer but Docker is already an approved
local runtime, build the exact reviewed commit with
`deploy/perclip-runtime.Dockerfile`. The base image is pinned by digest and
`deploy/perclip-runtime-requirements.txt` is the production-only export of
`server/uv.lock`. Render the reviewed
`deploy/perclip-ingest-container.service.in` and
`deploy/perclip-worker-container.service.in` templates with exact absolute
paths, numeric UID/GID, image tag, listener and private environment-file path;
never install a template with unresolved `@...@` placeholders.

```bash
docker build \
  --file deploy/perclip-runtime.Dockerfile \
  --build-arg "PERCLIP_COMMIT=<exact reviewed commit>" \
  --tag "perclip-runtime:<exact reviewed commit>" \
  .
```

Before deployment, verify:

- the image revision label equals the reviewed commit;
- Python is 3.11 or newer;
- every installed production package matches the exported lock;
- the image contains no environment file, token or user data;
- an isolated `--network none` import/preflight succeeds.

Systemd may then run one API container and one Worker container from that same
image. Use:

- host networking only to retain the existing API listener and reverse-proxy
  route;
- the existing private environment through `--env-file`;
- identical read-write bind mounts for the SQLite data directory and
  PersonalClips asset root;
- a read-only container root plus a bounded private `/tmp`;
- the explicitly reviewed numeric runtime UID/GID inside each container;
- distinct fixed container names and stop timeouts;
- no mount of the Docker socket inside either container.

Do not infer the runtime identity from an account name alone. Inspect the
existing unit's `User=`, live process UID/GID and the ownership/mode of both
bind roots. If the legacy process and a required 0700 asset root are
root-owned, preserving UID/GID 0 for the first cutover is safer than silently
changing ownership during the service pause. In that compatibility case,
require a read-only container root, `no-new-privileges`, exact bind mounts and
no Docker socket, and track conversion to a dedicated non-root identity as a
separate hardening stage.

This fallback creates no new reverse-proxy, DNS, port-forward or RAGFlow
container. Do not attach the PerClip containers to a RAGFlow-specific Docker
network. The three RAGFlow-off gates remain mandatory.

For a host where the deployment login has no general systemd privilege, install
`deploy/perclip-stage23-3a-control.sh` root-owned and pair it with a root-only
configuration containing exact candidate paths and SHA-256 values. Grant only
its named `check`, `pause`, `install-units`, `start-candidate`,
`stop-candidate`, `rollback` and `status` actions. The helper records and
restores the original unit state; it does not broaden authorization to
arbitrary units or shell commands.

## 10. Stage 23.3A deployed baseline

The 2026-07-25 personal-NAS cutover used the containerized fallback above
because the host provides Python 3.10 while PerClip requires Python 3.11 or
newer. Production runs one API and one Worker from exact image revision
`a351690a35b812b5356af76dc025da035081a7a8`. Both units are active/enabled,
share the same formal SQLite/asset roots and retain the previous API listener
and public HTTPS route.

The private environment is mode 600 and the effective processing boundary is:

```text
PERCLIP_PROCESSING_MODE=worker
RAGFLOW_MODE=off
PERCLIP_ENABLE_REAL_RAGFLOW_SYNC=0
PERCLIP_ENABLE_CLIP_TO_RAGFLOW=0
```

Retained server-side RAGFlow credentials may cause the read-only capability
report to say `http_skeleton/configured=true`; that does not override the
Worker's `RAGFLOW_MODE=off` short circuit. Acceptance must therefore check both
the effective mode/write gates and zero job/index-attempt evidence instead of
assuming the adapter will report `disabled`.

The exact final backup, restore helper and service rollback evidence stay in a
private NAS location. Repository records contain only counts and hashes.
Stage-specific backup hashes, formal acceptance and the non-destructive
rollback proof are in `docs/stage23-3a-unified-nas-cutover.md`.

## 11. Exact-allowlisted operator Worker

The ordinary HTTP adapter deliberately cannot activate a RAGFlow v0.26.1
Document because the public Chunk route strips vector fields. When one
reviewed Dataset must be enabled, render
`deploy/perclip-worker-operator-container.service.in` and use the
operator-verified Worker entrypoint included in the pinned runtime image.

The private environment must contain one and only one identical Dataset value
in both controls:

```text
RAGFLOW_MODE=index
PERCLIP_ENABLE_REAL_RAGFLOW_SYNC=1
PERCLIP_ENABLE_CLIP_TO_RAGFLOW=0
PERCLIP_RAGFLOW_SYNC_ALLOW_DATASET_IDS=<exact test Dataset>
PERCLIP_OPERATOR_ALLOW_DATASET_ID=<same exact test Dataset>
PERCLIP_OPERATOR_RAGFLOW_CONTAINER=<exact private container target>
PERCLIP_OPERATOR_SOCKET_PATH=/run/perclip/ragflow-operator.sock
PERCLIP_RAGFLOW_OPERATOR_VERIFIER_COMMAND_JSON=["python","/opt/perclip/server/tools/unix_ragflow_operator_verifier.py"]
```

The host proxy is lifecycle-bound to `perclip-worker.service`. It accepts only
bounded document requests over the private Unix socket and invokes only the
fixed read-only search-index verifier. The Worker container mounts that socket
file, not the Docker socket. It also does not mount the host verifier,
environment file as a filesystem path, SSH keys or RAGFlow storage.
The proxy runs as root only because it invokes the fixed Docker command; after
binding it assigns the mode-0600 socket to the configured Worker
UID/GID. If the proxy exits unexpectedly, it terminates the Worker container
command so systemd restarts the bounded pair.

Use `deploy/perclip-stage23-3b-control.sh` with a separate root-only control
configuration and rollback directory. Its candidate hashes cover the
environment, both units, runtime image revision, proxy and verifier. Before
replacement it records the currently deployed Stage 23.3A units, environment
and active/enabled state; `rollback` therefore returns to `worker/off/0/0`,
not to the historical inline service.
