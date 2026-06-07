PYTHON := .venv/bin/python
FRONTEND_DIR := aidm_frontend

.PHONY: install backend frontend unified test lint typecheck build bundle-budget smoke browser-smoke visual-smoke clean clean-deps source-archive db-upgrade health secrets api-types reproject-session reproject-all

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt
	cd $(FRONTEND_DIR) && npm ci

backend:
	./scripts/run_local_backend.sh

frontend:
	cd $(FRONTEND_DIR) && npm run dev -- --host 127.0.0.1

unified:
	./scripts/run_unified_local.sh

test:
	$(PYTHON) -m pytest

lint:
	cd $(FRONTEND_DIR) && npm run lint

typecheck:
	cd $(FRONTEND_DIR) && npm run typecheck

build:
	cd $(FRONTEND_DIR) && npm run build

bundle-budget:
	cd $(FRONTEND_DIR) && npm run bundle:budget

smoke:
	$(PYTHON) scripts/smoke_beta_flow.py

browser-smoke:
	cd $(FRONTEND_DIR) && npm run smoke:browser

visual-smoke:
	cd $(FRONTEND_DIR) && npm run smoke:visual

clean:
	./scripts/cleanup_artifacts.sh

clean-deps: clean
	rm -rf .venv $(FRONTEND_DIR)/node_modules
	@echo "Removed local dependency folders."

source-archive:
	./scripts/create_source_archive.sh

db-upgrade:
	FLASK_APP=aidm_server.main:create_app flask db upgrade

health:
	./scripts/check_local_health.sh

secrets:
	$(PYTHON) scripts/scan_secrets.py

api-types:
	$(PYTHON) scripts/generate_api_types.py

reproject-session:
	@if [ -z "$(SESSION_ID)" ]; then echo "SESSION_ID is required"; exit 1; fi
	$(PYTHON) scripts/reproject_session.py --session-id $(SESSION_ID)

reproject-all:
	$(PYTHON) scripts/reproject_session.py --all
