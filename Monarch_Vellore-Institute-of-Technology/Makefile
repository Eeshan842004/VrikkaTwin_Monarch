# VrikkaTwin task targets. Each target delegates to tasks.py, so Linux/CI (make) and Windows (python tasks.py)
# always run exactly the same steps.
PY ?= python

.PHONY: setup check-env data validate-db cohort features train eval tts api app demo test test-all lint all

setup check-env data validate-db cohort features train eval tts api app demo test test-all lint all:
	$(PY) tasks.py $@
