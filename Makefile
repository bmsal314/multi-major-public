.PHONY: setup dev test test-private test-db test-ui build audit release
setup:
	./setup.sh
dev:
	backend/.venv/bin/python scripts/dev.py
test:
	backend/.venv/bin/python -m pytest tests/cloud -q
	backend/.venv/bin/python -m scripts.generate_contracts --check
	npm --prefix frontend test
	npm --prefix frontend run test:security
test-private:
	backend/.venv/bin/python -m pytest backend/tests -q
test-db:
	backend/.venv/bin/python scripts/check_database.py
test-ui:
	backend/.venv/bin/python scripts/check_ui.py
build:
	npm --prefix frontend run build
audit:
	npm --prefix frontend audit
	backend/.venv/bin/pip-audit -r backend/requirements.lock --no-deps --disable-pip
release:
	backend/.venv/bin/python scripts/prepare_release.py --initialize
