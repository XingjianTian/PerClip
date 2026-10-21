# PerClip maintenance

The maintained repository is https://github.com/XingjianTian/PerClip.

Core Memory supports capture/share, durable local upload, server acceptance,
processing, Knowledge list, literal title search and detail readback. RAGFlow
is an optional server-side integration; it is not required for the core flow.

Private operational records, acquired browsing samples, recordings and old Git
history are held in a private archive. Do not merge old branches into this
repository. Recover needed changes as reviewed source patches only. The newer
optional worker durability patch and its offline tests are preserved separately
under deploy/ragflow-mac-worker; this migration does not deploy that worker.

Use the ignored local .env for endpoints, paths and credentials. Keep mobile
credentials separate from RAGFlow, embedding and connector credentials. Android
accepts the mobile API URL/token in local settings; no server secret is compiled
into its APK. No production service, user dataset or historical failed document
is modified by this publication work. Synthetic fixtures prove offline behavior,
not live platform compatibility or current production health.

Historical Stage 24/25 acquisition and live acceptance harnesses are retained
only in the private archive with their original browsing inputs and receipts.
They are retired from the public developer suite; no pass or skip is claimed
for those private historical checks. Product API, processing, safety and Android
regressions remain in the public source.
