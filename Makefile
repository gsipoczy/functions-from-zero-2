install:
	pip install --upgrade pip &&\
		pip install -r requirements.txt

test:
	pytest -vv --cov=main --cov=src test_all.py

lint:
	pylint --disable=R,C main.py src/*.py

format:
	black *.py src

all: install lint test format