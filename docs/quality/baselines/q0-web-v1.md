# PerClip Q0-Web baseline

- Fixture version: `q0-web-v1`
- PerClip commit: `df4108d9f13213dfd17f45bb97bb1da35ab4e8dc`
- Evaluator: `perclip-q0-evaluator/v2`
- Manifest SHA-256: `9247815c9cad5bb6beb6528919cb37d565ce78c03b3acb7ab01149d49f6a05aa`
- Cases: 26
- Comparison mode: `baseline` (26 baseline cases; no previous baseline)
- Comparison counts: improved 0 / unchanged 0 / regressed 0

## Contract and applicable metrics

- All-case contract match: 0 / 26 (0.0%)

| Metric | Passed | Eligible | Not applicable | Rate |
| --- | ---: | ---: | ---: | ---: |
| raw_asset_preservation | 26 | 26 | 0 | 100.0% |
| title_accuracy | 16 | 26 | 0 | 61.5% |
| body_anchors | 17 | 18 | 8 | 94.4% |
| noise_residue | 16 | 19 | 7 | 84.2% |
| canonical_url | 19 | 22 | 4 | 86.4% |
| state_calibration | 15 | 26 | 0 | 57.7% |
| safe_error | 7 | 8 | 18 | 87.5% |
| routing | 18 | 26 | 0 | 69.2% |
| recall_eligibility | 17 | 26 | 0 | 65.4% |
| projection_consumption | 26 | 26 | 0 | 100.0% |
| retry_idempotency | 26 | 26 | 0 | 100.0% |
| tags | 0 | 26 | 0 | 0.0% |

## Control metrics

- worker_claims_only_next_job: pass
- worker_recovery: pass
- stale_token_rejected: pass
- fake_ragflow_fault_isolation: pass

## Local fixture pipeline latency

- Local fixture pipeline p50: 17.66 ms
- Local fixture pipeline p95: 24.578 ms
- Scope: socket-free fixtures on the current test host.
- Excludes real DNS, public RTT/download, NAS I/O, OCR/ASR/LLM, and RAGFlow.
- This is only comparable within the same fixtures and test environment; it is not a home-NAS, cloud-server, production-SLO, or user-experience latency measurement.

| Stage | p50 ms | p95 ms |
| --- | ---: | ---: |
| archive_original | 2.267 | 4.769 |
| clean | 1.749 | 3.959 |
| enrich | 2.565 | 4.718 |
| extract | 2.594 | 5.121 |
| index | 1.677 | 2.676 |
| route | 3.703 | 6.692 |

## Main baseline failure categories

- title_accuracy: G10, G11, G12, G13, G14, G15, G16, G17, G21, G22
- body_anchors: G02
- noise_residue: G03, G04, G17
- canonical_url: G08, G18, G37
- state_calibration: G04, G05, G06, G07, G09, G17, G18, G19, G20, G38, G39
- safe_error: G17
- routing: G10, G11, G12, G13, G14, G15, G16, G17
- recall_eligibility: G10, G11, G12, G13, G14, G15, G16, G17, G22
- tags: G01, G02, G03, G04, G05, G06, G07, G08, G09, G10, G11, G12, G13, G14, G15, G16, G17, G18, G19, G20, G21, G22, G37, G38, G39, G40

## Per-case results

| ID | Expected | Actual | Safe error | Contract match | Failed applicable metrics |
| --- | --- | --- | --- | --- | --- |
| G01 | completed | completed | — | no | tags |
| G02 | completed | completed | — | no | body_anchors, tags |
| G03 | completed | completed | — | no | noise_residue, tags |
| G04 | completed | partial | — | no | noise_residue, state_calibration, tags |
| G05 | completed | partial | — | no | state_calibration, tags |
| G06 | completed | partial | — | no | state_calibration, tags |
| G07 | completed | partial | — | no | state_calibration, tags |
| G08 | partial | partial | — | no | canonical_url, tags |
| G09 | completed | partial | — | no | state_calibration, tags |
| G10 | failed | failed | redirect_limit_exceeded | no | title_accuracy, routing, recall_eligibility, tags |
| G11 | failed | failed | private_address_blocked | no | title_accuracy, routing, recall_eligibility, tags |
| G12 | failed | failed | private_address_blocked | no | title_accuracy, routing, recall_eligibility, tags |
| G13 | failed | failed | private_address_blocked | no | title_accuracy, routing, recall_eligibility, tags |
| G14 | failed | failed | web_fetch_failed | no | title_accuracy, routing, recall_eligibility, tags |
| G15 | failed | failed | response_too_large | no | title_accuracy, routing, recall_eligibility, tags |
| G16 | failed | failed | unsupported_content_type | no | title_accuracy, routing, recall_eligibility, tags |
| G17 | failed | partial:bin | — | no | title_accuracy, noise_residue, state_calibration, safe_error, routing, recall_eligibility, tags |
| G18 | completed | partial | — | no | canonical_url, state_calibration, tags |
| G19 | completed | partial | — | no | state_calibration, tags |
| G20 | completed | partial | — | no | state_calibration, tags |
| G21 | partial | partial | — | no | title_accuracy, tags |
| G22 | partial | partial | — | no | title_accuracy, recall_eligibility, tags |
| G37 | completed | completed | — | no | canonical_url, tags |
| G38 | completed | partial | — | no | state_calibration, tags |
| G39 | completed | partial | — | no | state_calibration, tags |
| G40 | completed | completed | — | no | tags |

Q0 is a measurement baseline, not a candidate-release claim. The current
extractor, cleaner, enricher, routing and Recall algorithms were not changed
to improve these results. No public web page or real external service was used.
