"""Quality cleanup rules for the extracted French translation.

The fan translation is a French localization of the official *English* script.
During review we found one mechanical inconsistency that can be fixed safely and
reproducibly without rewriting the text:

* The monster/entity concept ``原種`` ("Sephira" in the official English,
  singular "Sephira" / plural "Sephirot") is rendered three different ways in
  the French release: ``Sephira`` (mostly masculine singular, but feminine in
  a few battle tutorials, and occasionally used as a plural), ``Sephirot``
  (mostly plural, but sometimes singular) and ``Sephiroth`` (six occurrences,
  the Final Fantasy spelling).

This module normalises that terminology to the dominant, internally-consistent
form used by the majority of the release and by the official English:

* singular: ``Sephira`` (masculine)
* plural:   ``Sephirot``

It also fixes three concrete grammar slips found during the same review.

Every rule is an exact substring replacement, applied in the listed order, so
the result is deterministic and auditable.
"""

from __future__ import annotations

# Each entry: (find, replace, reason).
CLEANUP_RULES: list[tuple[str, str, str]] = [
    # -- "Sephiroth" -> canonical singular / plural -------------------------
    ("un Sephiroth", "un Sephira", "terminology: singular"),
    ("du Sephiroth", "du Sephira", "terminology: singular"),
    ("Ce Sephiroth", "Ce Sephira", "terminology: singular"),
    ("les Sephiroth", "les Sephirot", "terminology: plural"),
    # -- "Sephira" used as a plural -> canonical plural ---------------------
    ("tous les Sephira", "tous les Sephirot", "terminology: plural"),
    ("des Sephira", "des Sephirot", "terminology: plural"),
    ("les Sephira", "les Sephirot", "terminology: plural"),
    # -- feminine "Sephira" -> masculine (dominant gender) ------------------
    ("Cette Sephira", "Ce Sephira", "terminology: gender"),
    ("Une Sephira", "Un Sephira", "terminology: gender"),
    ("La Sephira", "Le Sephira", "terminology: gender"),
    ("On peut vraiment la vaincre", "On peut vraiment le vaincre", "terminology: gender"),
    ("Est-ce possible de la vaincre", "Est-ce possible de le vaincre", "terminology: gender"),
    # -- "Sephirot" used as a singular -> canonical singular ----------------
    ("un Sephirot", "un Sephira", "terminology: singular"),
    ("Le Sephirot", "Le Sephira", "terminology: singular"),
    # -- grammar slips ------------------------------------------------------
    ("j'ai le droit à", "j'ai droit à", "grammar: 'avoir droit à' (no article)"),
    ("affroentes", "affrontes", "typo"),
    ("combattre Sephirot", "combattre les Sephirot", "grammar: missing article"),
]

# Substrings that must never survive cleanup (validated after application).
FORBIDDEN_AFTER = ("Sephiroth",)

# --------------------------------------------------------------------------- #
# Font-compatibility fallback
#
# The game's bitmap font (mainfonthd720 / subfont_hd720) covers ASCII plus the
# handful of non-ASCII characters that already appear in the official English
# and Japanese scripts: ``é`` (U+00E9), the ellipsis ``…`` (U+2026) and the
# right single quote ``'`` (U+2019).  French-only accented characters are not in
# the font and render as the placeholder ``~`` at runtime, so they are mapped to
# their nearest ASCII equivalents.  ``é`` is deliberately kept because it exists
# in the official script and therefore in the font.
# --------------------------------------------------------------------------- #
ACCENT_FALLBACK_MAP: dict[str, str] = {
    "\u00e0": "a",  # à
    "\u00e2": "a",  # â
    "\u00c0": "A",  # À
    "\u00c2": "A",  # Â
    "\u00e7": "c",  # ç
    "\u00c7": "C",  # Ç
    "\u00e8": "e",  # è
    "\u00ea": "e",  # ê
    "\u00eb": "e",  # ë
    "\u00c8": "E",  # È
    "\u00ca": "E",  # Ê
    "\u00cb": "E",  # Ë
    "\u00c9": "E",  # É (uppercase is absent from the font)
    "\u00ee": "i",  # î
    "\u00ef": "i",  # ï
    "\u00ce": "I",  # Î
    "\u00cf": "I",  # Ï
    "\u00f4": "o",  # ô
    "\u00f6": "o",  # ö
    "\u00d4": "O",  # Ô
    "\u00f9": "u",  # ù
    "\u00fb": "u",  # û
    "\u00fc": "u",  # ü
    "\u00d9": "U",  # Ù
    "\u00db": "U",  # Û
    "\u00dc": "U",  # Ü
    "\u0153": "oe",  # œ
    "\u0152": "OE",  # Œ
    "\u00ab": "\"",  # «
    "\u00bb": "\"",  # »
    "\u2014": "-",  # — em dash
    "\u00d7": "x",  # ×
}

# Characters we intentionally keep (they exist in the official scripts).
KEPT_NON_ASCII = {"\u00e9", "\u2026", "\u2019"}  # é … '

# --------------------------------------------------------------------------- #
# Second Light mojibake fix
#
# The BLUE REFLECTION Second Light fan installer (BRSL_fr-FR_V1.02.beta.2)
# encodes a subset of the French accented characters with the wrong code points
# (the author's keyboard/tool mangled them).  Map them back to the correct
# French characters before the accent fallback runs, so the fallback then
# reduces them to ASCII as usual.
# --------------------------------------------------------------------------- #
BRSL_MOJIBAKE_MAP: dict[str, str] = {
    "\u00fd": "\u00e7",  # ý -> ç  ("ýa" -> "ça")
    "\u00df": "\u00ea",  # ß -> ê  ("peut-ßtre" -> "peut-être")
    "\u00f6": "\u00fb",  # ö -> û  ("sör" -> "sûr")
    "\u00e4": "\u00e2",  # ä -> â  ("gräce" -> "grâce")
    "\u00f3": "\u00f4",  # ó -> ô  ("plutót" -> "plutôt")
    "\u00e1": "\u00f9",  # á -> ù  ("oá" -> "où")
    "\u25cf": "\u0153",  # ● -> œ  ("C●urite" -> "Cœurite")
}

# Capital accented letters are mangled as "¤X¤" or "°X°" (a currency/degree
# sign on both sides of the base letter).
BRSL_MOJIBAKE_CAPITAL: tuple[tuple[str, str], ...] = (
    ("\u00a4A\u00a4", "\u00c0"),  # ¤A¤ -> À
    ("\u00a4E\u00a4", "\u00c9"),  # ¤E¤ -> É
    ("\u00a4C\u00a4", "\u00c7"),  # ¤C¤ -> Ç
    ("\u00a4I\u00a4", "\u00ce"),  # ¤I¤ -> Î
    ("\u00b0A\u00b0", "\u00c0"),  # °A° -> À
    ("\u00b0C\u00b0", "\u00c7"),  # °C° -> Ç
    ("\u00b0E\u00b0", "\u00c9"),  # °E° -> É
    ("\u00b0I\u00b0", "\u00ce"),  # °I° -> Î
    ("\u00b0O\u00b0", "\u00d4"),  # °O° -> Ô
    ("\u00b0U\u00b0", "\u00db"),  # °U° -> Û
)


def fix_brsl_mojibake(text: str) -> tuple[str, int]:
    """Undo the Second Light installer's accent mojibake."""
    result = text
    replaced = 0
    for find, replace in BRSL_MOJIBAKE_CAPITAL:
        count = result.count(find)
        if count:
            result = result.replace(find, replace)
            replaced += count
    chars: list[str] = []
    for char in result:
        replacement = BRSL_MOJIBAKE_MAP.get(char)
        if replacement is not None:
            chars.append(replacement)
            replaced += 1
        else:
            chars.append(char)
    return "".join(chars), replaced


def apply_accent_fallback(text: str) -> tuple[str, int]:
    """Replace French-only accented characters that the font cannot render."""
    replaced = 0
    result: list[str] = []
    for char in text:
        replacement = ACCENT_FALLBACK_MAP.get(char)
        if replacement is not None:
            result.append(replacement)
            replaced += 1
        else:
            result.append(char)
    return "".join(result), replaced


def apply_cleanup(text: str) -> tuple[str, list[str]]:
    """Apply every rule to ``text`` and return (result, applied_reasons)."""
    result = text
    applied: list[str] = []
    for find, replace, reason in CLEANUP_RULES:
        if find in result:
            result = result.replace(find, replace)
            applied.append(reason)
    return result, applied


def validate_cleanup(text: str) -> list[str]:
    """Return the forbidden patterns still present in ``text``."""
    problems = []
    for forbidden in FORBIDDEN_AFTER:
        if forbidden in text:
            problems.append(forbidden)
    return problems


def describe() -> list[dict[str, str]]:
    return [
        {"find": find, "replace": replace, "reason": reason}
        for find, replace, reason in CLEANUP_RULES
    ]


if __name__ == "__main__":
    import json

    print(json.dumps(describe(), ensure_ascii=False, indent=1))
