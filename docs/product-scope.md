# PerClip Product Scope

This document defines the commercial planning scope for PerClip. It is not an implementation spec for new features.

## Current source release

The current source-release line is PerClip `v0.3.0`. Android and Server use the
same product version: Android `versionName 0.3.0` with `versionCode 3`, and
Server package/API version `0.3.0`. This release preparation covers source and
an unsigned local Release candidate only; it does not sign or publish a formal
Android package, create a tag or GitHub Release, deploy services, or change
NAS, RAGFlow, databases, or real user data.

## What PerClip Is

PerClip is a mobile capture and private-ingest layer for personal knowledge bases.

It helps a user collect fragmented mobile content from Android apps, quick notes, files, images, audio, and screen context, then send those clips into a self-hosted ingest API. The ingest API stores original assets and metadata in user-owned infrastructure and can forward content into PersonalClips, RAGFlow, future RAGGraph, and optional publishing workflows.

The product promise is:

- fast capture on Android;
- user-owned storage and credentials;
- server-side integration with RAGFlow, ASR, archival, and automation;
- a stable path from raw mobile content to searchable private knowledge assets.

## What PerClip Is Not

PerClip is not:

- a public cloud note app;
- a hosted content custody service by default;
- a replacement for RAGFlow;
- a replacement for the WeChat bot path;
- a cloud account reseller that holds user master credentials;
- a generic social media automation farm;
- a consumer backup product for all phone data;
- a guarantee that third-party platforms permit automated publishing in every account or region.

## Target Users

Primary early users:

- knowledge workers who already maintain a NAS, private server, RAGFlow, or personal knowledge base;
- creators who collect mobile inspiration and later publish to Xiaohongshu, Zhihu, newsletters, or internal knowledge bases;
- consultants or operators who need phone-to-private-archive workflows for client research, evidence, and notes;
- technical users who want a private mobile capture layer without putting RAGFlow keys on a phone.

Commercial service buyers:

- individuals who want PerClip deployed on their own NAS or cloud host;
- small teams that want a private ingestion workflow with support, backup, and operations runbooks;
- customers who want optional plugin setup for RAGGraph, extraction, ASR, OCR, or publishing;
- organizations that need private deployment rather than a shared SaaS knowledge store.

Non-target users for the near term:

- users who want a fully managed public SaaS with no infrastructure ownership;
- users who need iOS support immediately;
- users who need guaranteed automated posting across every social platform;
- users who cannot operate or authorize any private server, NAS, or cloud resource.

## Current Product Boundary

Android owns:

- capture entry points;
- local review UI;
- local upload queue;
- mobile ingest token storage;
- network retry and recent upload state;
- source app, MIME, title hint, note, URL/text, and file payload collection.

Server ingest owns:

- bearer-token authentication;
- request and file size enforcement;
- MIME allowlist;
- idempotency and duplicate handling;
- local metadata persistence;
- local fallback asset storage;
- ClipToRAGFlow integration;
- server-side ASR credentials and processing;
- RAGFlow credentials and dataset integration.

Downstream systems own:

- PersonalClips archive layout;
- RAGFlow document indexing and retrieval;
- future RAGGraph graph construction;
- publishing plugin authorization and platform-specific behavior.

## Current Android Surface Structure

The Android app keeps four primary surfaces: 闪记, 知识库, 记忆星球, and 设置.
Settings Home is organized as ordinary rows rather than dashboard shortcut
cards:

- `连接与同步`: 连接设置、记忆抓取设置、知识库管理、记忆星球设置;
- `外观与辅助`: 主题颜色、减少动态效果;
- `诊断与关于`: 系统信息.

知识库管理 and 记忆星球设置 remain independent destination pages; only their
entry placement changes. Capture actions use `保存`, while network work is
described as background 同步/处理. Server integration names and route metadata
remain implementation contracts rather than ordinary-user navigation terms.

## Paid Service Boundaries

PerClip can charge for:

- deployment consultation and setup;
- NAS/private-server installation;
- HTTPS/reverse-proxy setup guidance;
- RAGFlow integration setup;
- backup, restore, upgrade, and token-rotation runbooks;
- support packages and operational health checks;
- optional extraction, ASR, OCR, RAGGraph, and publishing plugin packages;
- team/enterprise configuration, audit, and compliance documentation.

PerClip should not charge by taking ownership of:

- the user's cloud account;
- the user's domain registration account;
- the user's NAS admin password;
- the user's RAGFlow API key as a hosted secret in PerClip-operated infrastructure;
- the user's private content archive;
- social platform master credentials.

Allowed commercial model:

- The user contracts directly with cloud, NAS, domain, SMS, ASR, and AI providers.
- The user owns the infrastructure and receives the credentials.
- PerClip provides software, templates, scripts, support, plugin packaging, and deployment labor.
- Any support access is temporary, least-privilege, logged, and revocable.

Disallowed default model:

- PerClip operates a shared public ingestion endpoint that stores customer mobile tokens and forwards private content without a separate SaaS security and compliance program.
- PerClip stores RAGFlow, ASR, NAS, SSH, or cloud master credentials outside the user's environment.
- Android includes RAGFlow or ASR credentials.

## Product Language

Use these terms consistently:

- "mobile ingest token": the revocable credential stored on Android and checked by the PerClip ingest API.
- "server-side credentials": RAGFlow, ASR, NAS, archive, cloud, and publishing credentials that stay on the server or plugin host.
- "PersonalClips": the user-owned archive destination for original and derived clip assets.
- "clip metadata": normalized facts about a captured item, separate from the binary payload.
- "adapter": source-specific code that maps Android, WeChat bot, or future clients into the shared metadata contract.
- "plugin": optional downstream capability such as RAGGraph, OCR, ASR, or publishing.

## Near-Term Positioning

PerClip should be sold as "private mobile capture infrastructure for personal knowledge bases", not as a generic notes app.

The strongest commercial wedge is deployment and reliability:

- users already want RAGFlow/private knowledge bases;
- mobile capture remains painful;
- private deployment is high-trust and hard enough that service revenue is plausible;
- optional plugins can become paid add-ons after the ingest contract is stable.
