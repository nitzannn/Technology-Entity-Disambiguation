import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KB_PATH = ROOT / "src" / "techresolve" / "data" / "technologies.json"
GOLD_PATH = ROOT / "data" / "eval" / "gold.csv"
sys.path.insert(0, str(ROOT / "src"))

from techresolve import Resolver, ResolverConfig, build_kb  # noqa: E402

_default_resolver = None


def default_resolver() -> Resolver:
    global _default_resolver
    if _default_resolver is None:
        _default_resolver = Resolver.from_path()
    return _default_resolver


def entity(eid, name, aliases=(), parent=None, vendor="V", category="c"):
    return {"id": eid, "canonical_name": name, "vendor": vendor, "category": category,
            "parent_id": parent, "aliases": list(aliases)}


def small_resolver(*entities, **config) -> Resolver:
    kb = build_kb({"schema_version": 1, "entities": list(entities)})
    return Resolver(kb, ResolverConfig(**config))
