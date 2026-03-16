.PHONY: dev install lint docker-build docker-run

install:
	pip install -r requirements.txt

dev:
	uvicorn main:app --reload --host 0.0.0.0 --port $${HTTP_PORT:-8000}

lint:
	ruff check .
	ruff format --check .

docker-build:
	docker build -t openclaw-manager .

docker-run:
	docker run --rm --env-file .env -p 8000:8000 openclaw-manager
