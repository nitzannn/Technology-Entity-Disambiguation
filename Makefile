PY ?= python3
export PYTHONPATH := src

DEMO_INPUTS = "Amazon Web Services" "AWS EKS" "Sentinel" "Microsoft Sentinel" "SentinelOne" \
              "Crowdstrik Falcon" "Azure Sentinel" "Okta, Inc." "Apache Log4j 2.14.1" "FooBarDB"

.PHONY: all test eval eval-dev eval-test eval-sweep eval-save eval-diff demo resolve clean

all: test eval

test:
	$(PY) -m unittest discover -s tests -t tests -v

eval: eval-dev eval-test

eval-dev:
	$(PY) scripts/evaluate.py --split dev

# Final report. Never tune against this split.
eval-test:
	$(PY) scripts/evaluate.py --split test

eval-sweep:
	$(PY) scripts/evaluate.py --split dev --sweep --timing-repeats 0

eval-save:
	$(PY) scripts/evaluate.py --split all --timing-repeats 0 --save baseline.json

eval-diff:
	$(PY) scripts/evaluate.py --split all --timing-repeats 0 --baseline baseline.json --fail-on-regression

demo:
	$(PY) -m techresolve --compact $(DEMO_INPUTS)

# Resolve one name of your choice: make resolve NAME="AWS Cloud"
resolve:
	@test -n "$(NAME)" || { echo 'usage: make resolve NAME="AWS Cloud"'; exit 2; }
	$(PY) -m techresolve "$(NAME)"

clean:
	rm -rf baseline.json build dist src/*.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
