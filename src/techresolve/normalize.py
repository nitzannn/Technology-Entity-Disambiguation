"""Technical string normalization.

Normalization only removes *formatting* differences (case, unicode forms,
punctuation, spacing, trailing legal suffixes). Semantic variants ("Amazon Web Services" vs "AWS")
are KB aliases and are never encoded here. Version numbers and meaningful
words such as "cloud", "platform" or "service" are kept.
"""
from __future__ import annotations

import re
import unicodedata

_SYMBOLS = re.compile(r"[™®©℠]")
# "+" and "#" are kept because they carry identity in technology names
# (C, C++, C# must not collapse into the same key).
_PUNCT = re.compile(r"[^\w\s+#]|_")
_SPACES = re.compile(r"\s+")

# Only legal-entity suffixes, removed only from the end of the string.
# "limited" is left out: it is also an ordinary word in product names.
LEGAL_SUFFIXES = frozenset(
    {"inc", "incorporated", "ltd", "corp", "corporation", "llc", "plc"}
)


def normalize(text: str) -> str:
    """May return "" (e.g. for "Inc.")."""
    # Symbols are stripped before NFKC, which would rewrite "™" as the letters "TM".
    s = _SYMBOLS.sub("", text)
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("&", " and ")
    s = _PUNCT.sub(" ", s)
    tokens = s.casefold().split()
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)
