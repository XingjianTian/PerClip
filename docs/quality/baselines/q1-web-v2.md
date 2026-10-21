# q1-web-v2 baseline

- Schema: `perclip.quality-corpus-report.v2`
- Implementation commit: `293f3e61c44110d78f64e5c80ddd24ffd360b461`
- Manifest SHA-256: `316ed0a6090ecbcc922a8737e8ccb718190b52b4eb6e871015e4fdc6dd0d44bc`
- Mode: first Corpus v2 baseline; no relative Q0-Web v1 score is claimed
- Contract cases: 26/26 passed

| Case | Title applicable | Content title | Provenance | Processing | User status | Recall | Index | Match |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| G01 | yes | 离线队列复盘 | user.title_hint | completed | ready | yes | yes | pass |
| G02 | yes | 长文整理实验 | user.title_hint | completed | ready | yes | yes | pass |
| G03 | yes | 可恢复任务设计 | user.title_hint | completed | ready | yes | yes | pass |
| G04 | yes | 本地优先的知识整理 | html.title | completed | ready | yes | yes | pass |
| G05 | yes | 阅读清单工具发布测试版 | html.title | completed | ready | yes | yes | pass |
| G06 | yes | PerClip Fixture Runner | html.title | completed | ready | yes | yes | pass |
| G07 | yes | Idempotent request API | html.title | completed | ready | yes | yes | pass |
| G08 | yes | 内容清洗的边界 | html.title | partial | ready | yes | yes | pass |
| G09 | yes | 重定向后的规范地址 | html.title | completed | ready | yes | yes | pass |
| G10 | no | — | — | failed | needs_attention | no | no | pass |
| G11 | no | — | — | failed | needs_attention | no | no | pass |
| G12 | no | — | — | failed | needs_attention | no | no | pass |
| G13 | no | — | — | failed | needs_attention | no | no | pass |
| G14 | yes | Timeout research reference | user.title_hint | failed | needs_attention | no | no | pass |
| G15 | no | — | — | failed | needs_attention | no | no | pass |
| G16 | no | — | — | failed | needs_attention | no | no | pass |
| G17 | yes | unsupported.bin | file.filename | failed | needs_attention | no | no | pass |
| G18 | yes | 相对规范链接 | html.title | completed | ready | yes | yes | pass |
| G19 | yes | 如何判断网页正文提取质量？ | html.title | completed | ready | yes | yes | pass |
| G20 | yes | 三步整理每周阅读清单 | meta.og:title | completed | ready | yes | yes | pass |
| G21 | yes | 正文首句作为候选。 | body.first_line | partial | ready | yes | yes | pass |
| G22 | no | — | — | partial | needs_attention | no | no | pass |
| G37 | yes | 缓存刷新检查 | user.title_hint | completed | ready | yes | yes | pass |
| G38 | yes | 同一文章的两个入口 | html.title | completed | ready | yes | yes | pass |
| G39 | yes | Local-first 知识工作流 | html.title | completed | ready | yes | yes | pass |
| G40 | yes | 鲁棒清洗的压力样本 | html.title | completed | ready | yes | yes | pass |
