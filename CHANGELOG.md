# Changelog

## [0.3.0] - 2026-08-04

### Product baseline

- Carries the Stage 23.8 product cleanup baseline: frictionless local-first
  capture, shared Memory Detail, Knowledge local-first behavior, and the final
  Settings terminology/layout cleanup.
- Keeps the Android and Server source versions aligned at `0.3.0`.
- Uses Android `versionCode 3` for the next source-release line.

### Release boundary

- This is source-release preparation with a locally generated unsigned Release
  APK candidate.
- Signing, formal-package installation, tag creation, GitHub Release creation,
  deployment, NAS/RAGFlow changes, database mutation, and real-data operations
  are outside the scope.

### Verification

The local gate passed with Server `613`, WeChat bridge `56`, Android JVM
`451/0/0/0`, Debug lint, Debug/Release assembly, APK secret/brand/package
audits, Q2 production-default `60/60` primary accuracy with zero false
positives/privacy leaks, Q2 semantic-boundary `8/8` contract checks, lock/
compileall/shell syntax checks, and `git diff --check`. The unsigned candidate
is documented with its SHA-256 in the v0.3.0 release note (historical reference retained in the private archive),
the current [project handoff](HANDOFF.md), and `Records.md`.

## [0.2.0] - 2026-07-29

See docs/releases/v0.2.0.md (historical reference retained in the private archive).
