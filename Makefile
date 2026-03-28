.PHONY: run migrate shell test coverage lint build up down logs

# ─── Local development ──────────────────────────────────────────────────────

run:
	python manage.py runserver --settings=config.settings.development

migrate:
	python manage.py makemigrations --settings=config.settings.development
	python manage.py migrate --settings=config.settings.development

shell:
	python manage.py shell --settings=config.settings.development

createsuperuser:
	python manage.py createsuperuser --settings=config.settings.development

collectstatic:
	python manage.py collectstatic --noinput --settings=config.settings.production

# ─── Testing ────────────────────────────────────────────────────────────────

test:
	pytest

coverage:
	pytest --cov=apps --cov-report=html --cov-report=term-missing
	@echo "Coverage report generated in htmlcov/index.html"

# ─── Code quality ───────────────────────────────────────────────────────────

lint:
	flake8 apps/ config/

# ─── Docker ─────────────────────────────────────────────────────────────────

build:
	docker compose build

up:
	docker compose --profile dev up db web-dev

down:
	docker compose --profile dev down db web-dev

logs:
	docker compose logs -f web-dev

docker-migrate:
	docker compose exec web-dev python manage.py migrate --settings=config.settings.development

docker-shell:
	docker compose exec web-dev python manage.py shell --settings=config.settings.development

docker-test:
	docker compose exec web-dev pytest
