.PHONY: setup api worker test privacy-setup privacy-check configure
setup:
	uv sync --project server --extra dev
api:
	./scripts/run_server_local.sh
worker:
	./scripts/run_worker.sh
test:
	uv run --project server --no-env-file --extra dev pytest server/tests tests
privacy-setup:
	git config --local core.hooksPath .githooks
privacy-check:
	python3 scripts/check_privacy.py
configure:
	./scripts/with_env.sh python scripts/render_gateway.py
