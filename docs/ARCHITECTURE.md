# Architecture

## Components and data flows

```mermaid
flowchart LR
  subgraph Update["(a) Add or update entities"]
    direction TB
    P[Proposal<br/>analyst or review queue] --> H[Human review<br/>new entity · missing alias · ambiguous<br/>rename: old name becomes alias, id kept<br/>merge: redirect_to stub, old id still resolves]
    H --> PR[Git PR<br/>technologies.json + gold.csv rows]
    PR --> V[make test: KB validation<br/>ids, fields, refs, cycles, empty aliases]
    V --> E[make eval-diff: dev/test eval<br/>+ regression diff vs baseline · CI gate]
    E --> M[Merge → new kb_version<br/>sha256 of file]
  end

  subgraph Runtime["(b) Resolve an input string"]
    direction TB
    KB[(technologies.json)] --> L[kb.py<br/>load + validate<br/>redirects: merge aliases, rewrite parents]
    L --> IX[index.py<br/>exact · trigram]
    IN[raw string] --> R[resolver.py<br/>normalize → lookup → retrieve → score → decide]
    IX --> R
    CFG[config.py<br/>threshold · margin · K · weights] --> R
    R --> OUT[ResolveResult<br/>status · id · name · confidence · candidates<br/>kb_version · algorithm_version · config_hash]
    R -. ResolutionEvent .-> FO[production.py<br/>FanOutSink]
    FO -.-> MS[InMemoryMetrics]
    FO -. NOT_FOUND / AMBIGUOUS .-> RQ[ReviewQueue]
  end

  M --> KB
  RQ -. prioritized items .-> P

  subgraph Offline["Offline evaluation"]
    G[(gold.csv<br/>dev / test)] --> EV[evaluate.py<br/>P/R/F0.5 · Recall@K · rates · latency · diff]
  end
  EV -. calls resolve() .-> R
```

| Module | Responsibility |
|---|---|
| `config.py` | `ResolverConfig` (threshold, margin, K, weights) with validation; config hash and algorithm version |
| `normalize.py` | Technical normalization (`normalize`), including trailing legal-suffix stripping |
| `kb.py` | Loads and validates the KB; resolves redirect chains, merges stub aliases into the final target, rewrites `parent_id`s that name a stub; `lookup(id)` for old ids; computes the KB version |
| `index.py` | Builds `exact_alias_index` and `trigram_index` at load time |
| `retrieval.py` | At most K distinct alias strings, ranked by shared trigrams → trigram Jaccard → alias (strict cut) |
| `scoring.py` | Alias-level score: soft token Jaccard plus `SequenceMatcher` |
| `resolver.py` | Tier orchestration, max-per-entity aggregation, threshold and margin decision |
| `cli.py` | `techresolve` command: resolves names from arguments or stdin lines and prints JSON results (`--kb`, `--compact`) |
| `evaluation.py`, `scripts/evaluate.py` | Gold scoring rules, metrics, sweep, regression diff |
| `production.py` | `ResolutionEvent`, `MetricsSink` protocol, `InMemoryMetrics`, `ReviewQueue`, `FanOutSink` stubs |

## Resolution flow

```mermaid
flowchart TD
  subgraph S1["1 · Normalization"]
    N["normalize()<br/>strip ™®© → NFKC → &amp;→and → punct→space<br/>casefold → collapse spaces<br/>→ drop trailing Inc/Corp/LLC…"]
    E0{empty?}
  end
  subgraph S2["2 · Candidate retrieval"]
    X{exact_alias_index}
    LEN{"len ≥ min_fuzzy_len (4)?"}
    TG["trigram retrieval<br/>≤ K distinct aliases: rank by shared trigrams,<br/>then trigram Jaccard, then alias<br/>each alias → all its entity ids"]
  end
  subgraph S3["3 · Decision"]
    SC["alias score =<br/>0.5·soft_token_jaccard + 0.5·SequenceMatcher"]
    AG["entity score = max over its aliases<br/>rank by (−score, id)"]
    T{"best ≥ threshold (0.75)?"}
    C["contenders = entities with<br/>best − score &lt; margin (0.10), or tied with best"]
    D{"number of contenders"}
  end
  subgraph S4["4 · Canonical ID"]
    M["MATCH<br/>canonical_id + canonical_name<br/>e.g. aws/eks · AWS EKS"]
    AMB["AMBIGUOUS<br/>no ID · every candidate id with its score"]
    NF["NOT_FOUND<br/>no ID · top-3 near misses from the fuzzy path"]
  end

  A[input string] --> N --> E0
  E0 -- yes --> NF
  E0 -- no --> X
  X -- "1 id · exact, 1.0" --> M
  X -- "≥2 ids · shared alias" --> AMB
  X -- miss --> LEN
  LEN -- no --> NF
  LEN -- yes --> TG --> SC --> AG --> T
  T -- no --> NF
  T -- yes --> C --> D
  D -- "1 · fuzzy, score" --> M
  D -- "≥2" --> AMB
```

Traced through the bundled KB:

| Input | Normalized | Path | Result |
|---|---|---|---|
| Amazon EKS | `amazon eks` | exact | MATCH `aws/eks` (1.0) |
| Okta, Inc. | `okta` | exact, legal suffix stripped | MATCH `okta/workforce-identity` (1.0) |
| Crowdstrik Falcon | `crowdstrik falcon` | fuzzy | MATCH `crowdstrike/falcon` (0.986) |
| Sentinel | `sentinel` | exact, shared alias | AMBIGUOUS `microsoft/sentinel`, `sentinelone/singularity` |
| FooBarDB | `foobardb` | fuzzy, below threshold | NOT_FOUND (best 0.20) |
