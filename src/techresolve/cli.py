"""Command line: python -m techresolve "AWS Cloud" "Sentinel" ..."""
from __future__ import annotations

import argparse
import json
import sys

from .resolver import Resolver


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="techresolve", description="Resolve technology names to canonical IDs.")
    parser.add_argument("names", nargs="*", help="names to resolve (reads stdin lines if omitted)")
    parser.add_argument("--kb", default=None, help="KB JSON file (default: the KB bundled with the package)")
    parser.add_argument("--compact", action="store_true", help="one JSON object per line")
    args = parser.parse_args(argv)

    resolver = Resolver.from_path(args.kb)
    names = args.names or [line.rstrip("\n") for line in sys.stdin if line.strip()]
    for name in names:
        payload = resolver.resolve(name).to_dict()
        print(json.dumps(payload, sort_keys=True) if args.compact else json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
