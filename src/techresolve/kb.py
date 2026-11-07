"""Knowledge-base loading and validation.

The KB JSON file is the single source of truth. Indexes are derived from it
at load time (see index.py). The KB version is the SHA-256 of the exact file
bytes, so any edit produces a new version.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

from .normalize import normalize

log = logging.getLogger(__name__)

SUPPORTED_SCHEMA_VERSIONS = {1}


class KBValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Entity:
    id: str
    canonical_name: str
    vendor: str
    category: str
    parent_id: str | None
    aliases: tuple[str, ...]  # deduplicated by normalized form, canonical_name included

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "canonical_name": self.canonical_name,
            "vendor": self.vendor,
            "category": self.category,
            "parent_id": self.parent_id,
            "aliases": list(self.aliases),
        }


@dataclass(frozen=True)
class KnowledgeBase:
    version: str
    entities: dict[str, Entity]  # only real entities, keyed by id
    redirects: dict[str, str] = field(default_factory=dict)  # stub id -> final target id

    def final_id(self, entity_id: str) -> str:
        return self.redirects.get(entity_id, entity_id)

    def lookup(self, entity_id: str) -> Entity | None:
        """Map any known id (current or redirected) to its final entity; None if unknown."""
        return self.entities.get(self.final_id(entity_id))


def load_kb(path: str | Path | None = None) -> KnowledgeBase:
    """Load a KB file; with no path, the KB bundled as package data."""
    raw = Path(path).read_bytes() if path is not None else bundled_kb_bytes()
    version = hashlib.sha256(raw).hexdigest()
    return build_kb(json.loads(raw), version=version)


def bundled_kb_bytes() -> bytes:
    """The bundled KB (src/techresolve/data/technologies.json), read via importlib.resources
    so it works from a source checkout, an installed wheel, or a zip."""
    return files("techresolve").joinpath("data").joinpath("technologies.json").read_bytes()


def build_kb(data: dict, version: str = "inline") -> KnowledgeBase:
    """Validate a KB document and return an immutable KnowledgeBase.

    Redirect stubs ({id, redirect_to, aliases?}) mark merged or renamed
    entities. A stub's aliases (former names) are merged into its final
    target, and a parent_id that names a stub is rewritten to the final
    target, so the rest of the system only ever sees real entity ids.
    """
    if data.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        raise KBValidationError(f"unsupported schema_version: {data.get('schema_version')!r}")

    records: dict[str, dict] = {}
    raw_redirects: dict[str, str] = {}
    stub_aliases: dict[str, list[str]] = {}

    for record in data.get("entities", []):
        eid = record.get("id")
        if not eid or not isinstance(eid, str):
            raise KBValidationError(f"entity without a valid id: {record!r}")
        if eid in records or eid in raw_redirects:
            raise KBValidationError(f"duplicate id: {eid}")

        if "redirect_to" in record:
            extra = set(record) - {"id", "redirect_to", "aliases"}
            if extra:
                raise KBValidationError(f"redirect stub {eid} must not have fields {sorted(extra)}")
            raw_redirects[eid] = record["redirect_to"]
            stub_aliases[eid] = list(record.get("aliases", []))
            continue

        for required in ("canonical_name", "vendor", "category"):
            if not record.get(required):
                raise KBValidationError(f"{eid}: missing {required}")
        records[eid] = record

    redirects = {src: _follow_redirect(src, raw_redirects, records) for src in sorted(raw_redirects)}

    # Former names of merged entities become aliases of the final target.
    # Sorted by stub id so the merged alias order is deterministic.
    merged: dict[str, list[str]] = {}
    for src in sorted(stub_aliases):
        merged.setdefault(redirects[src], []).extend(stub_aliases[src])

    entities: dict[str, Entity] = {}
    for eid, record in records.items():
        parent_id = record.get("parent_id")
        if parent_id is not None:
            if parent_id not in records and parent_id not in redirects:
                raise KBValidationError(f"{eid}: parent_id {parent_id!r} is not a known id")
            parent_id = redirects.get(parent_id, parent_id)
            if parent_id == eid:
                raise KBValidationError(f"parent cycle: {eid} is its own parent after redirects")
        entities[eid] = Entity(
            id=eid,
            canonical_name=record["canonical_name"],
            vendor=record["vendor"],
            category=record["category"],
            parent_id=parent_id,
            aliases=_dedupe_aliases(eid, record["canonical_name"], record.get("aliases", []), merged.get(eid, [])),
        )

    _check_parent_cycles(entities)
    return KnowledgeBase(version=version, entities=entities, redirects=redirects)


def _dedupe_aliases(eid: str, canonical_name: str, own: list[str], merged: list[str]) -> tuple[str, ...]:
    """canonical_name first, then own aliases, then merged ones; unique by normalized form."""
    aliases: list[str] = []
    seen: set[str] = set()
    for alias in [canonical_name, *own]:
        norm = normalize(alias)
        if not norm:
            raise KBValidationError(f"{eid}: alias {alias!r} normalizes to an empty string")
        if norm in seen:
            if alias != canonical_name:
                log.warning("%s: duplicate alias %r ignored", eid, alias)
            continue
        seen.add(norm)
        aliases.append(alias)
    for alias in merged:
        norm = normalize(alias)
        if not norm:
            raise KBValidationError(f"{eid}: merged alias {alias!r} normalizes to an empty string")
        if norm not in seen:  # overlap with the target is expected after a merge
            seen.add(norm)
            aliases.append(alias)
    return tuple(aliases)


def _follow_redirect(src: str, redirects: dict[str, str], entities: dict[str, dict]) -> str:
    path = [src]
    current = redirects[src]
    while current in redirects:
        if current in path:
            raise KBValidationError(f"redirect cycle: {' -> '.join(path + [current])}")
        path.append(current)
        current = redirects[current]
    if current not in entities:
        raise KBValidationError(f"redirect {src} points to unknown id {current!r}")
    return current


def _check_parent_cycles(entities: dict[str, Entity]) -> None:
    for start in sorted(entities):
        seen = {start}
        current = entities[start].parent_id
        while current is not None:
            if current in seen:
                raise KBValidationError(f"parent cycle involving {start}")
            seen.add(current)
            current = entities[current].parent_id
