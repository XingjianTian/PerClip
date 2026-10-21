# Fixed Topics and Memory Planet

Stage 23.1 adds a server-owned fixed-topic domain and a read-only Memory Planet
projection. It is additive to Core, Knowledge and Recall. The code taxonomy is
bootstrap data only: after first initialization, SQLite is the runtime
authority. This stage does not add an Android production UI or change a
production Dataset.

## Pipeline boundary

Core processing is:

```text
archive_original → extract → clean → enrich → classify_topic → route
```

`route` still marks Core ready. `index` remains an independent task and is not
a Core readiness gate. Topic classification reads only the active, usable
whole-memory Clean/Enrich projection. It never reads RAGFlow Chunks and never
uses RAGFlow retrieval.

Failed extraction, unusable partial content and raw fallback content do not
enter classification, Recall or indexing. A classification failure records a
safe failed attempt, keeps any prior active assignment and continues to route,
so clean content is not lost. A successful new generation replaces the active
automatic assignment. Retries use a stable run key and do not create duplicate
runs.

## Taxonomy

Taxonomy version `perclip.fixed-topics.v1` contains 15 user topics plus
`unclassified`:

| ID | Display name |
| --- | --- |
| `ai_ml` | AI与大模型 |
| `digital_tech` | 数码与科技 |
| `software_automation` | 软件开发与自动化 |
| `education_research` | 教学与科研 |
| `work_projects` | 工作与项目 |
| `finance_economy` | 投资与经济 |
| `health_medical` | 健康与医疗 |
| `travel_places` | 旅行与地点 |
| `football_sports` | 足球与体育 |
| `games_entertainment` | 游戏与娱乐 |
| `history_culture` | 历史与文化 |
| `relationships` | 人际与关系 |
| `lifestyle` | 生活方式 |
| `beauty_fashion` | 美妆与穿搭 |
| `growth_reflection` | 个人成长与思考 |
| `unclassified` | 待归类 |

Each registry row has a stable ID, display name, description, positive
examples, exclusions, enabled state, sort order and taxonomy version. Aliases
are separately typed as `exact_alias`, `entity_hint` or `user_rule`. Ordinary
startup uses insert-if-absent and never overwrites operator changes. A
classification-affecting edit advances the runtime registry revision; a
display-name-only edit does not.

AI-related aliases resolve to `ai_ml`. `ChatGPT`, `Kimi`, `Claude`, `DeepSeek`
and `Codex` remain named entities and provide a high-confidence AI candidate;
they are not collapsed into the topic label. Entities and keywords are
supporting metadata, not primary themes.

## Classification providers and lifecycle

The production-default decision chain is:

1. `UserOverrideClassifier`
2. exact user rule
3. exact alias/entity rule through `ExactRuleClassifier`
4. deterministic `unclassified` fallback

An optional, direct server-side `OpenAICompatibleEmbeddingProvider` may be
inserted between exact matching and the fallback. It is disabled by default,
has bounded input, timeout/retry and response validation, caches topic
prototypes by taxonomy version, and fails open to exact/unclassified. Its
endpoint, key and model are server configuration only. The deterministic fake
provider is used only by the semantic-boundary contract tests and is not
evidence of model quality.

The exact classifier consumes one bounded versioned whole-memory projection:
explicit user title, active title, active summary, user tags, bounded clean
Markdown, and optional Knowledge Base name/source as weak context. It records
only the projection hash. Raw paths and secrets are scrubbed and are never
persisted as classifier input. Title and summary carry more weight than body
mentions; exclusions, negation, disabled-topic filtering, top-one/top-two
margin, secondary threshold and stable topic-ID tie-breaking are deterministic.

The persistence model is additive:

- `topic_definitions`
- `topic_aliases`
- `topic_classification_runs`
- `clip_topic_assignments`
- `clip_entities`
- `clip_keywords`

Run history distinguishes latest attempted and latest successful work.
Assignments identify the active primary/secondary rows and whether they are a
manual override. A manual override wins across later content generations and
is copied forward by a classification candidate without being replaced by an
automatic result. A failed reclassification leaves the previous active rows
unchanged.

Output limits are one primary topic, zero to two secondary topics, zero to
eight entities and zero to twelve keywords. Low-confidence content becomes
`unclassified`; it is never force-fit.

Personal logistic regression remains a design gate, not an implementation in
this stage. It may be introduced only after at least 50 manually confirmed
examples spanning at least five topics with at least five examples per topic,
using versioned embeddings and training/evaluation evidence.

## Public API

The additive `perclip.topic-assignment.v1` projection is included in full and
compact quality reads:

```json
{
  "contract_version": "perclip.topic-assignment.v1",
  "primary": {
    "topic_id": "ai_ml",
    "display_name": "AI与大模型",
    "source": "exact_rule"
  },
  "secondary": [],
  "entities": ["Claude", "Codex"],
  "keywords": [],
  "unclassified": false,
  "stale": false,
  "active_generation": "gen_…",
  "assignment_generation": "tag_…",
  "active_taxonomy_version": "perclip.fixed-topics.v1.r3",
  "latest_attempted_status": "succeeded",
  "latest_attempted_generation": "gen_…",
  "latest_safe_error": "",
  "topic_disabled": false,
  "manual_override": false,
  "classifier_source": "exact_rule"
}
```

It intentionally excludes confidence, engine, run ID and database identity.
`PUT /api/clips/{clip_id}/topic-assignment` accepts one registry topic ID and
creates a persistent manual override only when that topic exists and is
enabled. `DELETE /api/clips/{clip_id}/topic-assignment` clears it and restores
the latest successful automatic assignment. The authenticated registry
surface is:

- `GET /api/topics`
- `PATCH /api/topics/{topic_id}`
- `POST /api/topics/{topic_id}/aliases`
- `DELETE /api/topics/{topic_id}/aliases/{alias_id}`
- `POST /api/topic-rules`
- `DELETE /api/topic-rules/{rule_id}`

Classification-affecting edits enqueue eligible memories for
reclassification, except disabling a topic is deliberately prospective.
Existing assignments to a disabled topic remain visible with
`topic_disabled=true`; the topic simply cannot receive a new automatic or
manual assignment. Re-enabling or editing its matching behavior can enqueue a
fresh classification. All returned Clip IDs are public `pc_…` identities.

## Memory Planet

`perclip.app.v1.features.memory_planet` is optional. New services advertise
`true`; old services may omit it. Clients must not call the endpoint when the
field is missing or false.

`GET /api/memory-planet` accepts `week`, `month` or a bounded custom calendar
window. Custom requires inclusive `start=YYYY-MM-DD`,
`end=YYYY-MM-DD` and an IANA `timezone`, validates order and a maximum of 90
days, and returns the actual local dates, inclusive day count, time zone and
UTC half-open boundaries. Week/month reject custom parameters and retain their
existing semantics. An optional `knowledge_base_id` scopes the projection to
one active Knowledge Base. The selected ID is echoed in
`planet.window.knowledge_base_id`; a missing library is `404`, and an archived
library is `409`. Scope resolution accepts either the canonical
`clip_knowledge_bases` association or a completed enrichment for the selected
library so older completed records remain queryable during association
backfill.

Eligible memories must be Core ready, Recall eligible, have an active primary
assignment, not be persistently suppressed, and fall inside the window.
Temporary `defer` remains only a ranking/recency signal and does not remove a
memory from the eligible set.

At most five topics are returned. Topics and memories are never invented to
fill a quota. Topic ranking uses:

```text
0.40 coverage
+ 0.25 recency
+ 0.20 not recently surfaced
+ 0.10 user priority
+ 0.05 internal diversity
```

Each topic returns at most five unique, high-similarity-deduplicated memories:
up to two newest, two representative and one longest not recently surfaced.
`unclassified` may occupy a main topic slot only when it has at least three
memories or at least 20% of eligible memories. Smaller groups never disappear:
the response always includes `unclassified_count`, up to three
`unclassified_preview` memories, and `has_more_unclassified`. Persistently
suppressed and privacy-ineligible memories are filtered before Planet and
resurface. The response exposes only public Clip IDs and user-facing content;
internal IDs, classifier diagnostics, confidence and index details remain
private.

`suppress` and `restore` are accepted by the idempotent Recall interaction
endpoint. Suppression is stored independently from interaction history so it
survives process restart and exact request replay. It does not delete or
modify the Clip, Knowledge association, source asset, topic assignment or
index. `GET /api/recall/suppressions` is the authenticated recovery surface and
returns public Clip IDs only through bounded directional keyset pages. Opaque
previous/next cursors contain no internal Clip identity and allow complete
recovery without an aggregate client cap; `restore` makes the Clip eligible
again.

## RAGFlow propagation

Normal environments build RAGFlow `topic_ids` only from the active canonical
assignment. Metadata also carries `topic_taxonomy_version` and the opaque
`topic_assignment_generation`. There is no reverse flow from RAGFlow into
topics. The same canonical provenance is used in `isolated-staging`; that
environment isolates storage and allowlists the synthetic Dataset, but does
not substitute a different topic-assignment contract.

The indexed generation key includes topic IDs, taxonomy version and assignment
generation. Primary/secondary, taxonomy or manual-override changes therefore
create a distinct intent and remote Document. Only a fully verified replacement
advances `active_indexes`; failure keeps the old verified pointer. A
display-name-only edit does not advance taxonomy or force an index rebuild; the
new label is read directly from the registry and remote metadata may wait for a
future generation. `off` and `qa` still make zero remote calls.

## Q2 evidence

Q2 is intentionally split:

- `q2-production-default-v1` contains 60 synthetic cases and uses only the
  production-default manual → user-rule → exact alias/entity → unclassified
  chain. It reports exact-rule coverage, primary accuracy, unclassified rate,
  false-positive rate, hard-negative accuracy, ambiguous top-two accuracy,
  repeat stability and privacy leakage. The current local result is 0.8667
  exact-rule coverage, 1.0 primary/hard-negative/ambiguous accuracy, 0.1333
  unclassified rate, 0.0 false-positive rate and zero privacy leakage.
- `q2-semantic-boundary-v1` contains deterministic fake-provider cases for
  repeatability, threshold and fail-open fallback only. Its report explicitly
  sets `represents_model_quality=false`.

The corpus covers semantic-without-alias text, dual topics, negation,
exclusions, AI-phone/stock/teaching conflicts, technology-company finance,
project retrospectives, travel/history, new entities, short/noisy/bilingual
input, secret markers, manual overrides, disabled topics, alias and user-rule
edits, and taxonomy changes.

## Isolated verification evidence

The Stage 23.1 candidate was exercised in a dedicated NAS runtime with separate
source, SQLite, assets, logs, token, processes and port. The production service
remained active, and no old PersonalClips storage, “个人收藏” Dataset,
production database or real content was mounted or read.

With `RAGFLOW_MODE=off`, 46 fictional API ingests reached Core, Knowledge,
eligible Recall and the week/month/custom Planet reads with zero index
attempts. The corpus covered all 15 configured topics with at least two old
assignments per topic, cross-topic and semantic-boundary cases, manual
correction, alias/rule edits, unclassified output and prospective disabling.
No embedding provider was configured, so this run makes no external-model
quality claim and incurred no provider call.

Guarded index mode then verified 12 synthetic Documents in only the existing
allowlisted test Dataset. All active Documents carried canonical topic IDs,
runtime taxonomy and assignment generation. Manual correction and generation
replacement preserved the prior active pointer until a replacement verified;
an injected failed reclassification preserved the prior active assignment.
Exact cleanup covered the 12 originals plus two replacement Documents. All 14
attempts reached `deleted_verified`, repeated cleanup was idempotent, and the
final exact-Dataset audit returned the retained baseline of 8 Documents, 8
public/operator Chunks, 8 vectors, complete coverage and zero orphan Chunks.

On a physical Android device, the isolated application ID captured 13
fictional shares without altering the installed formal package. The first 12
uploaded and completed classification/routing while indexing stayed off. A
manual correction changed the Planet projection. Dark mode, 1.3x font,
rotation, background restore and visible-text privacy passed. The thirteenth
share remained Waiting while the isolated API was stopped, then became
Uploaded after recovery; the server advanced by exactly one Clip/receipt and
completed classification/routing once.
