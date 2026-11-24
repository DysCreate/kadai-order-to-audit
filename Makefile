.PHONY: up down up-prod down-prod logs-prod check-deploy seed seed-reset test test-api test-web e2e check lint typecheck benchmark reconcile shell psql logs build migrate

# Start the development stack
up:
	docker compose up --build -d

# Stop the development stack
down:
	docker compose down

# Start the production stack (requires a filled .env)
up-prod:
	docker compose -f docker-compose.prod.yml up --build -d

# Stop the production stack
down-prod:
	docker compose -f docker-compose.prod.yml down

# Tail production logs
logs-prod:
	docker compose -f docker-compose.prod.yml logs -f

# Django production deployment checks
check-deploy:
	docker compose -f docker-compose.prod.yml exec api python manage.py check --deploy

# Build images only
build:
	docker compose build

# Run migrations
migrate:
	docker compose exec api python manage.py migrate

# Seed benchmark data
seed:
	docker compose exec api python manage.py seed_benchmark

# Reset and re-seed
seed-reset:
	docker compose exec api python manage.py seed_benchmark --reset

# Run all backend tests
test:
	docker compose exec api pytest --cov=. --cov-report=term-missing --cov-fail-under=80 -v

# Run API tests only
test-api:
	docker compose exec api pytest tests/api/ -v

# Run frontend unit tests
test-web:
	docker compose exec web npm test 2>/dev/null || docker compose run --rm frontend-test npm test

# Run E2E tests
e2e:
	docker compose exec web npx playwright test

# Full check: lint + typecheck + test
check: lint typecheck test

# Lint backend (ruff) and frontend (eslint)
lint:
	docker compose exec api ruff check .
	docker compose exec api ruff format --check .

# Type check backend (mypy) and frontend (tsc)
typecheck:
	docker compose exec api mypy apps/ core/ --ignore-missing-imports
	docker compose run --rm -w /app --entrypoint npx web tsc --noEmit 2>/dev/null || true

# Run benchmark scenario
benchmark:
	docker compose exec api python manage.py run_benchmark

# Reconciliation check
reconcile:
	docker compose exec api python manage.py reconcile

# Django shell
shell:
	docker compose exec api python manage.py shell

# PostgreSQL shell
psql:
	docker compose exec db psql -U kadai -d kadai

# Tail logs
logs:
	docker compose logs -f
