lint:
	pylint --rcfile=.pylintrc main.py modules
test:
	pytest -v --timeout=10
