# Environment configuration

Copy the root `.env.example` to the ignored `.env`, set permission 0600, and
replace the mobile token placeholder with an independent random local value.
The API rejects the unchanged example token. Do not copy a production `.env`
into tests or share it in issues, logs, screenshots or handoff records.

`scripts/with_env.sh COMMAND ...` uses `uv run --project server --env-file .env`
and adds the local server source root to PYTHONPATH. It does not evaluate shell
commands in the file. Override the private file location with PERCLIP_ENV_FILE.
The template in server/.env.example is a compatibility pointer to the root file.

- API bind address, port, metadata and asset roots belong in `.env`.
- Android stores only its mobile API URL/token in local app settings. The emulator
  address 10.0.2.2 is a documented emulator bridge, not a personal deployment IP.
- Optional RAGFlow, ASR, embedding and connector endpoints/keys remain server-side.
  RAGFlow real mutation gates and exact dataset allowlists remain enforced.
- Standard public provider protocol URLs in parsers are compatibility constants;
  they are not private deployment endpoints. Server controls already accept
  environment overrides where providers support configurable endpoints.

`make configure` renders the optional OpenResty manager configuration into
ignored deploy/generated/openresty. This preserves Nginx variables such as $host
and substitutes only the named PerClip deployment variables. Host fields support
DNS names and IPv4; IPv6 gateway rendering is not supported. File mode is 0600
and generated output is not included in Git or the Docker build context.
Install generated configuration and private environment files only through your
own reviewed deployment process; rendering does not restart or deploy anything.
Systemd/container templates already receive their runtime values from an explicit
private EnvironmentFile/--env-file. Their /opt and /etc paths are reference layout,
not a record of the author's machine.

To apply mobile development settings to an explicitly selected debug device, the
operator may set ANDROID_SERIAL and invoke scripts/configure_debug_app_settings.sh.
That helper loads the private file and writes only mobile settings, never RAGFlow,
ASR, embedding or connector credentials. It does not run during normal setup.

Unit tests and privacy checks use `--no-env-file`; they do not inherit real service
configuration from an implicit dotenv hook. Service startup explicitly loads `.env`.
