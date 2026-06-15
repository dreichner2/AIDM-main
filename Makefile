PYTHON := .venv/bin/python
FRONTEND_DIR := aidm_frontend

.PHONY: install backend frontend unified test lint typecheck build bundle-budget smoke scenario-regression backup-restore-drill browser-smoke visual-smoke clean clean-deps source-archive db-upgrade health secrets api-types dev-check closed-beta-rc closed-beta-rc-fast deployment-readiness observability-check reproject-session reproject-all

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

scenario-regression:
	$(PYTHON) scripts/scenario_regression.py

backup-restore-drill:
	$(PYTHON) scripts/backup_restore_drill.py $(BACKUP_RESTORE_DRILL_ARGS)

observability-check:
	$(PYTHON) scripts/check_observability_bundle.py $(OBSERVABILITY_CHECK_ARGS)

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

dev-check:
	$(PYTHON) -m compileall -q aidm_server scripts
	$(PYTHON) -m ruff check --select E9,F63,F7,F82 aidm_server tests scripts
	$(PYTHON) scripts/scan_secrets.py
	$(PYTHON) scripts/generate_api_types.py --check
	$(PYTHON) scripts/check_observability_bundle.py
	cd $(FRONTEND_DIR) && npm run typecheck
	cd $(FRONTEND_DIR) && npm run lint

closed-beta-rc:
	$(PYTHON) scripts/closed_beta_rc_check.py --python $(PYTHON)

closed-beta-rc-fast:
	$(PYTHON) scripts/closed_beta_rc_check.py --python $(PYTHON) --skip-browser-smoke --skip-dependency-audits

deployment-readiness:
	$(PYTHON) scripts/deployment_readiness_check.py $(DEPLOYMENT_READINESS_ARGS)

reproject-session:
	@if [ -z "$(SESSION_ID)" ]; then echo "SESSION_ID is required"; exit 1; fi
	$(PYTHON) scripts/reproject_session.py --session-id $(SESSION_ID)

reproject-all:
	$(PYTHON) scripts/reproject_session.py --all
