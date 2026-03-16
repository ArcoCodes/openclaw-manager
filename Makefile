.PHONY: dev install lint docker-build docker-run

install:
	pip install -r requirements.txt

dev:
	env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
		python3 main.py

lint:
	ruff check .
	ruff format --check .

docker-build:
	docker build -t openclaw-manager .

docker-run:
	docker run --rm --env-file .env -p 8888:8888 openclaw-manager
