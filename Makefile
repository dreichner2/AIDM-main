PYTHON := .venv/bin/python
FRONTEND_DIR := aidm_frontend

.PHONY: install backend frontend test lint typecheck build bundle-budget smoke clean db-upgrade health secrets

install:
	python3 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt
	cd $(FRONTEND_DIR) && npm ci

backend:
	./scripts/run_local_backend.sh

frontend:
	cd $(FRONTEND_DIR) && npm run dev -- --host 127.0.0.1

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

clean:
	./scripts/cleanup_artifacts.sh

db-upgrade:
	FLASK_APP=aidm_server.main:create_app flask db upgrade

health:
	./scripts/check_local_health.sh

secrets:
	$(PYTHON) scripts/scan_secrets.py
