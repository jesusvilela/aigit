.PHONY: bootstrap up improve

bootstrap:
	./scripts/bootstrap_uv.sh --sync-only

up:
	UV_CACHE_DIR=$${UV_CACHE_DIR:-$(CURDIR)/.aigit/uv-cache} $${HOME}/.local/bin/uv run aigit up

improve:
	UV_CACHE_DIR=$${UV_CACHE_DIR:-$(CURDIR)/.aigit/uv-cache} $${HOME}/.local/bin/uv run aigit improve