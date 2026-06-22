# Evidence Lab — deployment & customization helpers.
#
# The customization overlay syncs a separate repo (e.g. wfp-evidencelab-custom)
# into the git-ignored ./custom directory, then layers it onto the production
# build and runtime. See docs/deployment/customization.md.
#
# Typical use on a deployment host:
#   make prod-up CUSTOM=/path/to/your-evidencelab-custom

CUSTOM ?=

COMPOSE_PROD := docker compose -f docker-compose.prod.yml
ENV_ARG :=

# Layer the deployment's compose override / env file when present in ./custom.
ifneq ($(wildcard custom/deploy/docker-compose.override.yml),)
  COMPOSE_PROD := $(COMPOSE_PROD) -f custom/deploy/docker-compose.override.yml
endif
ifneq ($(wildcard custom/env/.env),)
  ENV_ARG := --env-file custom/env/.env
endif

.PHONY: customize render-config prod-build prod-up prod-down

## customize: sync the CUSTOM repo into ./custom and render the resolved config.
customize:
	@if [ -z "$(CUSTOM)" ]; then \
	  echo "Set CUSTOM=/path/to/your-evidencelab-custom checkout" >&2; exit 1; fi
	@command -v rsync >/dev/null 2>&1 || { echo "rsync is required" >&2; exit 1; }
	rsync -a --exclude='.git' "$(CUSTOM)/" custom/
	@$(MAKE) render-config

## render-config: deep-merge config.json + custom/config.overlay.json.
render-config:
	python scripts/custom/merge_config.py \
	  --base config.json \
	  --overlay custom/config.overlay.json \
	  --out custom/config.resolved.json

## prod-build: build the production images with the overlay applied.
prod-build: render-config
	$(COMPOSE_PROD) build

## prod-up: build and start the production stack with the overlay applied.
prod-up: render-config
	$(COMPOSE_PROD) $(ENV_ARG) up -d --build

## prod-down: stop the production stack.
prod-down:
	$(COMPOSE_PROD) down
