# techresolve: Technology Entity Disambiguation

This tool turns technology names pulled from threat-intel reports into stable canonical IDs. It is deterministic, uses only the Python standard library, and gives every result an explanation.

- Design (one page): [docs/DESIGN.md](docs/DESIGN.md)
- Architecture diagram (Mermaid): [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- Resolution flow diagram: [docs/ARCHITECTURE.md#resolution-flow](docs/ARCHITECTURE.md#resolution-flow)

## Scope of this submission

Prioritized: the core resolver (normalization, retrieval, scoring, the ambiguity
decision), clear KB scope and naming rules, and an evaluation harness that keeps
precision honest (held-out test split, seen/novel breakdown, regression diff).

Deliberately left out:
- UI and production-scale ingestion (out of scope per the brief).
- LLMs or embeddings at runtime, so resolution stays deterministic and costs nothing.
- Version extraction and context-aware scoring (see Limitations in docs/DESIGN.md).
- Persistence for metrics and the review queue: `production.py` has the interfaces
  and in-memory stubs, with comments describing the production version.

## Install

You need Python 3.10+. There are no runtime dependencies.

```sh
python3 -m pip install .           # from the repo root; the KB ships inside the package
techresolve "AWS Cloud" "Sentinel" # works from any directory once installed
```

Without installing, run from the repo root with `PYTHONPATH=src python3 -m techresolve "AWS Cloud"`.

## Run

You need Python 3.10+ and `make`. From the repo root, run everything (tests, both evaluations, demo) with:

```sh
make test eval demo
```

All targets:

```sh
make               # tests and both evaluations
make test          # unit tests
make eval          # dev and test split reports, run separately
make eval-sweep    # threshold × margin (selected by F0.5) and K grid, dev split only (test is refused)
make demo          # resolve sample inputs and print JSON
make resolve NAME="AWS Cloud"     # resolve one name of your choice (pretty JSON)
make eval-save     # save current outcomes to baseline.json (run before your change)
make eval-diff     # after your change: diff against baseline.json, fail on regressions
make clean         # remove caches, build output and baseline.json
```

## Interface

```python
from techresolve import resolve, lookup_id, Resolver, ResolverConfig

resolve("Amazon Web Services").to_dict()
# {"status": "MATCH", "canonical_id": "aws", "canonical_name": "AWS", "confidence": 1.0,
#  "match_type": "exact", "candidates": [{"id": "aws", "score": 1.0}],
#  "kb_version": "…", "algorithm_version": "1.1.0", "config_hash": "…", ...}

resolve("Sentinel").status          # AMBIGUOUS: candidates microsoft/sentinel, sentinelone/singularity
resolve("Crowdstrik Falcon")        # MATCH crowdstrike/falcon, fuzzy, confidence 0.986
resolve("FooBarDB").status          # NOT_FOUND, with the top-3 near misses attached for review

# Map an ID stored before a merge or rename to its current entity (None if never known).
lookup_id("microsoft/azure-sentinel").id   # "microsoft/sentinel"

Resolver.from_path("my_kb.json", ResolverConfig(threshold=0.7, margin=0.1)).resolve("AWS EKS")
```

`ResolverConfig` rejects invalid values with `ValueError`. `confidence` is a similarity score between 0 and 1. It is 1.0 for exact hits. It is **not** a probability.

## Layout

```
src/techresolve/data/technologies.json  KB, the single source of truth (shipped as package data)
data/eval/gold.csv                      hand-labeled gold set with dev/test split (repo only, not shipped)
src/techresolve/                        normalize · kb · index · retrieval · scoring · resolver · evaluation · production · cli
scripts/evaluate.py                     evaluation CLI (metrics, sweep, save and baseline diff)
tests/                                  unittest suites
docs/                                   DESIGN.md, ARCHITECTURE.md
```

## Current results (threshold 0.75, margin 0.10, K=25)

| split | rows | P | R | F0.5 | accuracy | novel-form recall |
|---|---|---|---|---|---|---|
| dev (used for tuning) | 102 | 100% | 92.8% | 98.5% | 95.1% | 79.2% |
| test (never tuned on) | 79 | 100% | 78.9% | 94.9% | 84.8% | 64.7% |

Neither split has a false positive. Every miss is NOT_FOUND.
- **Novel-form recall:** recall on inputs that exact lookup can't resolve. Use it to judge generalization. Rows the lookup resolves score 100% on both splits.
- **Known misses:**
  - **Extra descriptive words** ("Kubernetes cluster", "VMware ESXi hypervisor"): 8 of 18 resolved on test. The correct entity is ranked first in every miss, but its score falls below the threshold.
  - **Version numbers** attached to the name. Out of scope by design.
  - **One typo transposition** ("Atlassian Jria").
- **Dataset caveat:** the KB and gold set share an author. The test split is the held-out check.

## Adding or merging technologies

1. Edit `src/techresolve/data/technologies.json`. Add an entity, or add aliases to an existing one. Never reuse an ID.
   - **Merge or rename:** replace the old entity with a stub, `{"id": "<old>", "redirect_to": "<new>", "aliases": [<former names>]}`.
   - The stub's aliases are merged into the final target, and redirect chains are followed.
   - A `parent_id` that names a stub is rewritten to the target.
   - `lookup_id("<old>")` keeps working.
2. Add gold rows that cover the change to `data/eval/gold.csv`, labeled by what the name means.
3. Run `make eval-save` on the base branch, then `make test eval eval-diff` on yours. Review any regressions and any newly AMBIGUOUS rows.
