"""Evaluation CLI.

  python scripts/evaluate.py --split dev --sweep        # tune threshold/margin on dev
  python scripts/evaluate.py --split test               # final report (never tune on this)
  python scripts/evaluate.py --split all --save base.json
  python scripts/evaluate.py --split all --baseline base.json [--fail-on-regression]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, replace
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
# The gold set is a repo (dev-time) asset and is not shipped with the package.
DEFAULT_GOLD_PATH = REPO / "data" / "eval" / "gold.csv"

from techresolve import ResolverConfig, Resolver, load_kb  # noqa: E402
from techresolve.evaluation import (  # noqa: E402
    Outcome,
    diff_against_baseline,
    evaluate,
    load_gold,
)

SWEEP_THRESHOLDS = (0.70, 0.75, 0.80, 0.85, 0.90, 0.95)
SWEEP_MARGINS = (0.0, 0.02, 0.05, 0.08, 0.10)
RECALL_K_VALUES = (1, 5, 10, 25, 50)


def pct(x):
    return "  n/a" if x is None else f"{100 * x:5.1f}%"


def print_report(report: dict, split: str, build_ms: float) -> None:
    print(f"== split={split}  rows={report['rows']}")
    print(f"   kb_version={report['kb_version'][:12]}  algorithm={report['algorithm_version']}  config={report['config_hash']}")
    print(f"   config: {asdict(report['config'])}")
    print(f"   FP={report['fp']} (MATCH with a wrong id: the critical error) of {report['tp'] + report['fp']} MATCH answers   "
          f"by expected status: {report['fp_by_expected'] or '{}'}")
    print(f"   precision {pct(report['precision'])}   recall {pct(report['recall'])}   F0.5 {pct(report['f05'])}   accuracy {pct(report['accuracy'])}")
    print(f"   TP={report['tp']}  FN={report['fn']}")
    print(f"   AMBIGUOUS rate {pct(report['ambiguous_rate'])}   NOT_FOUND rate {pct(report['not_found_rate'])}")
    print(f"   candidate Recall@K {pct(report['recall_at_k'])} (n={report['recall_at_k_n']})   "
          f"ambiguous candidate Recall@K {pct(report['ambiguous_recall_at_k'])} (n={report['ambiguous_recall_at_k_n']})")
    print("   per category (correct/total):")
    for cat, (ok, total) in report["per_category"].items():
        print(f"     {cat:15} {ok:3}/{total:<3} {pct(ok / total)}")
    print("   generalization (seen = exact lookup alone covers the surface form; novel = it does not):")
    for name, m in report["by_surface"].items():
        print(f"     {name:15} rows={m['rows']:3}  accuracy {pct(m['accuracy'])}  precision {pct(m['precision'])}  "
              f"recall {pct(m['recall'])}  FP={m['fp']} FN={m['fn']}")
    if "latency" in report:
        lat = report["latency"]
        print(f"   latency: p50 {lat['p50_ms']:.3f} ms  p95 {lat['p95_ms']:.3f} ms  p99 {lat['p99_ms']:.3f} ms  "
              f"({lat['calls']} calls)   index build {build_ms:.1f} ms")
    if report["errors"]:
        print("   errors:")
        for err in report["errors"]:
            tag = "FP" if err["fp"] else "FN" if err["fn"] else "  "
            print(f"     [{tag:5}] {err['category']:14} {err['input']!r:36} expected {err['expected']:52} got {err['got']}")


def run_sweep(kb, base: ResolverConfig, rows) -> None:
    print("== threshold x margin sweep")
    print("   thr   margin  FP     prec    rec     F0.5    AMB     NF      FN")
    grid = []
    for thr in SWEEP_THRESHOLDS:
        for margin in SWEEP_MARGINS:
            r = evaluate(Resolver(kb, replace(base, threshold=thr, margin=margin)), rows)
            grid.append((thr, margin, r))
            print(f"   {thr:.2f}  {margin:.2f}   {r['fp']:3}    {pct(r['precision'])}  {pct(r['recall'])}  "
                  f"{pct(r['f05'])}  {pct(r['ambiguous_rate'])}  {pct(r['not_found_rate'])}  {r['fn']:3}")
    # Selection rule: highest F0.5 (precision weighted 2x recall); ties go to the stricter
    # (higher threshold, wider margin) config.
    thr, margin, r = max(grid, key=lambda g: (g[2]["f05"], g[0], g[1]))
    print(f"   best: threshold={thr:.2f} margin={margin:.2f}  FP={r['fp']}  F0.5 {pct(r['f05'])}  recall {pct(r['recall'])}")
    print("== K sweep (candidate recall and end-to-end impact)")
    print("   K     Recall@K  ambRecall@K  prec    rec     F0.5    AMB     FP  FN")
    for k in RECALL_K_VALUES:
        r = evaluate(Resolver(kb, replace(base, top_k=k)), rows)
        print(f"   {k:<4}  {pct(r['recall_at_k'])}    {pct(r['ambiguous_recall_at_k'])}       "
              f"{pct(r['precision'])}  {pct(r['recall'])}  {pct(r['f05'])}  {pct(r['ambiguous_rate'])}  {r['fp']:3} {r['fn']:3}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "test", "all"), default="dev")
    parser.add_argument("--kb", default=None, help="KB JSON file (default: bundled KB)")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD_PATH))
    parser.add_argument("--sweep", action="store_true", help="threshold/margin/K grid (use on dev only)")
    parser.add_argument("--save", help="write outcomes to this JSON file (baseline for later diffs)")
    parser.add_argument("--baseline", help="compare against outcomes saved with --save")
    parser.add_argument("--fail-on-regression", action="store_true", help="exit 1 if the diff has regressions (CI)")
    parser.add_argument("--timing-repeats", type=int, default=50)
    args = parser.parse_args(argv)

    if args.sweep and args.split == "test":
        parser.error("refusing to tune on the test split")

    rows = load_gold(args.gold, args.split)
    kb = load_kb(args.kb)
    start = time.perf_counter()
    resolver = Resolver(kb)
    build_ms = (time.perf_counter() - start) * 1e3

    report = evaluate(resolver, rows, timing_repeats=args.timing_repeats)
    print_report(report, args.split, build_ms)
    if args.sweep:
        run_sweep(kb, resolver.config, rows)

    if args.save:
        payload = {
            "kb_version": report["kb_version"],
            "algorithm_version": report["algorithm_version"],
            "config_hash": report["config_hash"],
            "split": args.split,
            "outcomes": {k: v.to_dict() for k, v in report["outcomes"].items()},
        }
        Path(args.save).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        print(f"== saved outcomes to {args.save}")

    if args.baseline:
        saved = json.loads(Path(args.baseline).read_text())
        baseline = {k: Outcome.from_dict(v) for k, v in saved["outcomes"].items()}
        diff = diff_against_baseline(rows, baseline, report["outcomes"])
        print(f"== regression diff vs baseline kb={saved['kb_version'][:12]} config={saved['config_hash']}")
        for kind in ("improvement", "regression", "neutral"):
            print(f"   {kind}: {len(diff[kind])}")
            for change in diff[kind]:
                b, a = change["before"], change["after"]
                print(f"     {change['input']!r}: {b['status']} {b['canonical_id'] or b['candidate_ids']} -> "
                      f"{a['status']} {a['canonical_id'] or a['candidate_ids']}")
        if diff["new_fp"]:
            print(f"   NEW FP (blocking): {diff['new_fp']}")
        if diff["new_ambiguous"]:
            print(f"   newly AMBIGUOUS (review whether genuinely ambiguous): {diff['new_ambiguous']}")
        if diff["new_rows"]:
            print(f"   rows not in baseline: {len(diff['new_rows'])}")
        if args.fail_on_regression and (diff["regression"] or diff["new_fp"]):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
