# Makefile for RAG against the machine

PYTHON := uv run python
MODULE := src
MAX_CHUNK_SIZE ?= 2000
K ?= 10
DATASET ?= data/datasets/UnansweredQuestions/dataset_docs_public.json
TRUTH ?= data/datasets/AnsweredQuestions/dataset_docs_public.json
SCOPE ?= UnansweredQuestions

.PHONY: install run debug clean lint lint-strict test index search-dataset evaluate answer-dataset serve workbench

install:
	uv sync

run:
	$(PYTHON) -m $(MODULE)

debug:
	$(PYTHON) -m pdb -m $(MODULE) index --max_chunk_size $(MAX_CHUNK_SIZE)

clean:
	find . -type d -name "__pycache__" -not -path "./data/*" -not -path "./.venv/*" -exec rm -rf {} +
	rm -rf .mypy_cache .pytest_cache .ruff_cache

lint:
	uv run flake8 .
	uv run mypy . --warn-return-any --warn-unused-ignores --ignore-missing-imports --disallow-untyped-defs --check-untyped-defs

lint-strict:
	uv run flake8 .
	uv run mypy . --strict

test:
	uv run pytest -q

index:
	$(PYTHON) -m $(MODULE) index --max_chunk_size $(MAX_CHUNK_SIZE)

search-dataset:
	$(PYTHON) -m $(MODULE) search_dataset --dataset_path $(DATASET) --k $(K) --save_directory data/output/search_results/$(SCOPE)

evaluate:
	$(PYTHON) -m $(MODULE) evaluate --student_search_results_path data/output/search_results/$(SCOPE)/$(notdir $(DATASET)) --dataset_path $(TRUTH)

answer-dataset:
	$(PYTHON) -m $(MODULE) answer_dataset --student_search_results_path data/output/search_results/$(SCOPE)/$(notdir $(DATASET)) --save_directory data/output/search_results_and_answer/$(SCOPE)

serve:
	$(PYTHON) -m $(MODULE) serve --port 8000

workbench:
	$(PYTHON) -m workbench --port 8000
