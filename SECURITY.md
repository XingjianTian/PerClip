# Security Policy

## Secret Handling

PerClip deliberately separates mobile credentials from server-side credentials.

- Android App may store only the mobile ingest token.
- RAGFlow API keys, dataset IDs, Baidu ASR keys, NAS paths and archive credentials stay on the server side.
- Real environment files such as `server/.env` must not be committed.
- Use `server/.env.example` for templates and `scripts/generate_mobile_token.sh --env` for production mobile tokens.

## Files That Must Stay Local

The repository ignores these by default:

- `server/.env`
- `android/local.properties`
- virtual environments and caches
- build outputs, APKs, AABs and handoff bundles
- keystores, certificates and local override files
- runtime data under `server/data/`

Before publishing or sharing a branch, run:

```bash
git status --short --ignored
git ls-files --others --exclude-standard
```

Then verify that no ignored secret file is staged.

## Android Token Boundary

The mobile ingest token is not a RAGFlow API key. Treat it as a revocable upload credential:

- rotate it if a phone is lost or a debug build leaks;
- do not reuse cloud, NAS, SSH or RAGFlow passwords as the mobile token;
- prefer HTTPS for public endpoints;
- use LAN or Tailscale for private deployments when possible.

## Server Boundary

The ingest API authenticates mobile uploads with bearer token authentication. Production deployments should additionally use:

- HTTPS reverse proxy;
- request body and file size limits;
- least-privilege systemd user;
- environment file permissions set to `600`;
- regular token rotation;
- separate credentials for RAGFlow, ASR and cloud providers.

## Reporting

This is currently a private early-stage project. Report security issues directly to the repository owner rather than opening public issues.
