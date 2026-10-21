# PerClip / RAGFlow Boundary

PerClip is the system of record. RAGFlow is a replaceable search index. This
boundary applies to the P0 index-correctness implementation and to the isolated
staging verifier; neither changes the production deployment.

## Ownership

PerClip owns:

- public Clip and generation identities;
- source assets, clean projections, processing history, quality and routing;
- Knowledge Base associations and their immutable association intents;
- index attempts, retry state and the one active serving pointer;
- the exact metadata and content hash expected in each remote Document.

RAGFlow owns only the derived Dataset, Document, Chunk and vector structures
needed for retrieval. A RAGFlow upload response, parse request or `done` run is
not sufficient evidence that a generation is indexed.

## Activation contract

An attempt becomes `indexed_verified` and may replace the active pointer only
when one exact remote Document:

1. is in the intended Dataset and has matching
   `perclip-ragflow-index.v1` metadata;
2. reports remote run state `done`;
3. has a positive Chunk count with complete, non-duplicated page coverage; and
4. has exactly one search-index vector for every covered Chunk.

Failure, timeout or unsupported evidence preserves the previous active
generation. Detaching an association removes the active pointer immediately;
remote cleanup is a separate, retryable operation.

The public RAGFlow v0.26.1 Chunk route can prove Chunk coverage but strips its
real `q_<dimension>_vec` fields. Its `available` value is a Chunk availability
switch, not vector evidence. The normal HTTP adapter therefore fails closed on
vector verification.

## Isolated operator verifier

Staging can explicitly wrap the normal adapter with
`OperatorVerifiedRagflowAdapter`. The wrapper invokes a separately configured,
read-only command and requires the command to return
`perclip-ragflow-operator-evidence.v1`.

The verifier:

- accepts raw Dataset and Document identifiers only over JSON standard input;
- enforces an exact Dataset allowlist;
- queries the exact Document scope in the search index;
- requires every returned Chunk to belong to that Dataset and Document;
- counts exactly one `q_<dimension>_vec` field per covered Chunk;
- returns only SHA-256 aliases, counts and a fixed evidence type; and
- rejects identity mismatches, malformed evidence and partial coverage.

Command transport failures and timeouts are retryable. Malformed or
identity-mismatched evidence is unsupported and terminal for that attempt.
This verifier is staging-only evidence, not a public RAGFlow capability and not
an authorization to mutate any other Dataset.

### Formal NAS transport

Stage 23.3B reuses the same evidence contract without exposing the Docker
socket to either PerClip container. The Worker unit starts one root-owned host
proxy and the one pinned Worker container under the same systemd lifecycle.
The proxy:

- reads only the sole sync allowlist entry, a matching operator allowlist
  entry and the exact RAGFlow container target from the mode-0600 environment;
- accepts bounded document-scope requests over a mode-0600 Unix socket;
- assigns that socket only to the configured Worker UID/GID;
- rejects every Dataset other than that one exact identifier before invoking
  Docker;
- runs only the fixed read-only verifier bootstrap in the configured RAGFlow
  container; and
- returns only the validated evidence schema, identity aliases and counts.

The socket is mounted as a single file into the Worker container. The Docker
socket, host environment file, verifier source, SSH material and other host
paths are not mounted. A second Stage 23.3B scoped helper verifies the exact
image, unit, environment, proxy and verifier hashes and records the deployed
Stage 23.3A units/environment as its rollback target.
An unexpected proxy exit terminates the Worker command, letting systemd restart
both halves under the same lifecycle rather than leaving an unverifiable
Worker running. An intentional systemd stop sets the shared shutdown event
before stopping the proxy, so the same thread exit is not falsely reported as
an unexpected failure.

## Core availability

`archive_original → extract → clean → enrich → classify_topic → route` is the
Core path.
Knowledge and Recall become available after routing. Index is an independent
external job:

- `RAGFLOW_MODE=off` performs no RAGFlow call.
- `RAGFLOW_MODE=qa` reports capability only and performs no index call.
- `RAGFLOW_MODE=index` still requires the real-sync gate and exact Dataset
  allowlist.

An offline or unsupported RAGFlow service may delay indexing but cannot revoke
usable PerClip content. Failed extraction with raw fallback remains readable in
Knowledge but is not eligible for Recall or indexing.

## Privacy and operational boundary

Committed evidence may contain stable SHA-256 aliases and aggregate counts. It
must not contain raw Dataset or Document identifiers, hostnames, addresses,
credentials, SSH details, private paths, content returned from existing
Datasets or user data.

The formal Stage 23.3B run created only six retained fictional synthetic
records in the exact-allowlisted test Dataset. It did not read content from,
write to, parse, reindex or delete any non-target Dataset. The daily default
PerClip Knowledge Base remained unmapped and the 72 historical Clips were not
queued, reprocessed or indexed. Shared RAGFlow services, images, networks and
configuration were not restarted or changed.
