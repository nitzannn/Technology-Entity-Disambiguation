# Design: Technology Entity Disambiguation

**Approach.** Deterministic, stdlib only: normalize (trailing legal suffixes dropped) → exact alias lookup → stop if under 4 characters → trigram retrieval (≤ K aliases) → fuzzy score → best alias per entity → threshold + margin. Returns `MATCH`, `AMBIGUOUS` or `NOT_FOUND` with candidates, scores, KB hash, algorithm version and config hash. No LLMs or randomness at runtime.

**Scope.** An entity is a technology product at the granularity where vulnerabilities are tracked (roughly a CPE product). Versions, editions, modules, bare vendors, categories ("EDR") and languages ("Java", "C++": the name alone doesn't say which runtime is deployed) are not entities; runtimes and libraries are (Node.js, jQuery).
- Cloud and on-prem split only when the vendor sells separately named products (Exchange Server / Online); deployment options stay one entity (Jira).
- Appliance names are aliases of the OS that CVEs target (FortiGate → FortiOS).
- `parent_id` marks a native service inside a platform (AWS EKS, Sentinel under Azure), not a dependency or a shared vendor.

**Canonical names** (linted). `<Vendor> <Product>` in official casing (CrowdStrike Falcon, PAN-OS); no vendor when the product is the brand or vendor-neutral (Slack, Kubernetes); cloud services take the platform prefix (AWS EKS); no versions. Renames keep the ID and turn the old name into an alias.

**Data structures.** A JSON KB is the source of truth. `Entity(id, canonical_name, vendor, category, parent_id, aliases)` is immutable with stable slug IDs (`aws/eks`). Merges are `{id, redirect_to, aliases}` stubs, so old IDs still resolve. Loading rejects duplicates, dangling references, cycles and empty aliases, then builds normalized alias → `frozenset` of IDs and trigram → aliases. An alias with several IDs is a collision → `AMBIGUOUS` ("Sentinel").

**Decisions and trade-offs.**
- **Normalization ≠ synonyms.** Only formatting is removed (™, NFKC, punctuation except `+#`, case, trailing Inc/Corp/LLC…); synonyms are KB aliases.
- **Scoring.** `0.5·soft token Jaccard + 0.5·SequenceMatcher`; tokens pair one-to-one at ≥ 0.8, tokens of ≤ 3 characters only exactly ("eks" ≠ "ecs").
- **Ambiguity.** Below 0.75 → `NOT_FOUND` with top 3 for review. Every entity within 0.10 of the best, and every tie, is a contender; more than one → `AMBIGUOUS`. Never guess.
- **Precision vs. recall.** An FP is a silent miss: the real product goes unlinked, alerts fire for software the customer doesn't run, and a `MATCH` is never reviewed. An FN is a visible miss: `NOT_FOUND`/`AMBIGUOUS` lands in the review queue with candidates and is fixed by one alias, but its alerts are lost until someone does. Threshold and margin are tuned on dev by F0.5, which weights precision twice as heavily as recall.
- **Retrieval.** Fuzzy scoring every alias is too slow at scale, so a trigram index picks K = 25 candidate aliases and only those are scored. A shared alias is cut as one unit, so competitors survive (tested). Dev Recall@K is 100% from K = 1; 25 is headroom.
- **Updates.** `NOT_FOUND`/`AMBIGUOUS` feed a review queue; a human approves a PR to the KB and gold rows; `make eval-diff` fails on regressions (the CI gate). Nothing is auto-added.

**Scaling (100k+).** Indexes are built once when the KB loads; each query only reads them. Exact lookups stay O(1). Retrieval touches only the posting lists of the query's trigrams, and fuzzy scoring is capped at K candidates instead of every alias. Scoring one query–alias pair costs about O(|q|·|a|) in their lengths (`SequenceMatcher` plus token pairing) and does not depend on KB size, so a query costs O(K·|q|·|a|).

**Evaluation.** 181 hand-labeled rows (102 dev / 79 test). Tuning uses dev only; sweeps refuse test. Results are split into *seen* (lookup solves it) and *novel*. Reports P/R/F0.5, per-category accuracy, outcome rates, Recall@K, latency, and a per-row regression diff (`--baseline`). The scope change relabeled 10 rows without retuning.

| Split | Precision | Recall | F0.5 | Novel recall |
|---|---|---|---|---|
| Dev | 100% | 92.8% | 98.5% | 79.2% |
| Test | 100% | 78.9% | 94.9% | 64.7% |

Latency p50 0.003 ms, p99 ≈ 1 ms; index build ≈ 2 ms.

**Limitations.** Extra words ("Kubernetes cluster") went 8/18 on test, though the right entity ranked first in all 10 misses. No FPs on either split at threshold 0.75; at 0.70, "Microsoft Defender for Identity" (dev) and "Microsoft Defender for Cloud" (test), both out of KB, matched Defender for Endpoint. No version extraction; Confluence Server/Cloud not separated. One author wrote the KB and gold set; the test split is small. Next: alias-containment scoring, version extraction, vendor hints.

**Possible extension.** Serve the KB through a CRUD API with a review UI; edits still pass load validation and `make eval-diff` before merge.
