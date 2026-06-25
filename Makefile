install:
	pip install --upgrade pip &&\
		pip install -r requirements.txt

test:
	pytest -vv --cov=. --cov=src --cov=lib test_all.py || true

lint:
	pylint --disable=R,C main.py src/*.py lib/*.py

format:
	black *.py src lib

all: install lint test format