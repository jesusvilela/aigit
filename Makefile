.PHONY: bootstrap up improve merge-driver-eval

bootstrap:
	./scripts/bootstrap_uv.sh --sync-only

up:
	UV_CACHE_DIR=$${UV_CACHE_DIR:-$(CURDIR)/.aigit/uv-cache} $${HOME}/.local/bin/uv run aigit up

improve:
	UV_CACHE_DIR=$${UV_CACHE_DIR:-$(CURDIR)/.aigit/uv-cache} $${HOME}/.local/bin/uv run aigit improve

# Reproduce docs/evals/results/2026-10-15-merge-driver (about ten minutes).
MERGE_EVAL := docs/evals/results/2026-10-15-merge-driver
merge-driver-eval:
	python3 experiments/merge_driver/replay.py --trials 150 --seed 4 --out $(MERGE_EVAL)/data
	python3 experiments/merge_driver/algorithms.py --trials 400 --seed 2 --out $(MERGE_EVAL)/data
	python3 experiments/merge_driver/sweep.py --out $(MERGE_EVAL)/data
	python3 experiments/merge_driver/scaling.py --sizes 10,25,50,100,200 --repeats 3 --out $(MERGE_EVAL)/data
	python3 experiments/merge_driver/plots.py --data $(MERGE_EVAL)/data --out $(MERGE_EVAL)/figures
