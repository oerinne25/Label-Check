"""Beverage-type rules: which elements a label must carry, per TTB.

matching.py answers "does the label agree with the application?".
This module answers a different question: "does the label carry everything
the regulations require for this kind of product?" - so a required element
that's missing from the label is caught even when the application field
was left blank.

Sources (ttb.gov):
  Distilled spirits - 27 CFR part 5 (5.63 same field of vision, 5.65 alcohol
                      content, 5.66-5.68 name and address, 5.70 net contents)
  Wine              - 27 CFR part 4 (4.32 mandatory information, 4.36 alcohol
                      content: required above 14%; optional at 7-14% when
                      "table wine"/"light wine" is the designation)
  Malt beverages    - 27 CFR part 7 (7.63 mandatory information; alcohol
                      content required only when alcohol comes from added
                      flavors, otherwise optional; "ABV" not allowed, 7.65)
  All               - 27 CFR part 16 health warning (checked in matching.py)

Only elements that can be recognised from label text without knowing the
application value are presence-checked here. Brand name and class/type have
no fixed wording, so they're only checked when the application supplies them.
"""

from __future__ import annotations

import re

from .matching import FAIL, PASS, REVIEW, FieldResult, _ABV_RE, _num, clean_text, parse_volumes

SPIRITS, WINE, BEER, UNSPECIFIED = "spirits", "wine", "beer", "unspecified"

BEVERAGE_LABELS = {
    SPIRITS: "Distilled spirits",
    WINE: "Wine",
    BEER: "Beer / malt beverage",
    UNSPECIFIED: "Not specified",
}

_ALIASES = {
    "spirits": SPIRITS, "distilled spirits": SPIRITS, "spirit": SPIRITS, "ds": SPIRITS,
    "wine": WINE, "wines": WINE,
    "beer": BEER, "malt beverage": BEER, "malt beverages": BEER, "malt": BEER,
    "beer / malt beverage": BEER, "beer/malt beverage": BEER,
}

# "Bottled by", "Distilled and Bottled by", "Brewed & Bottled by", "Imported by"...
_NAME_ADDRESS_RE = re.compile(
    r"\b(bottled|distilled|produced|imported|brewed|vinted|cellared|packed|blended|made|"
    r"prepared|manufactured|filled|canned)\s+(?:(?:and|&)\s+\w+\s+)?by\b",
    re.IGNORECASE,
)
_IMPORTED_RE = re.compile(r"\bimported\b", re.IGNORECASE)
_COUNTRY_RE = re.compile(
    r"\b(product of|produce of|produced in|made in|distilled in|brewed in|bottled in|imported from)\s+\w",
    re.IGNORECASE,
)
_SULFITES_RE = re.compile(r"contains\s+sul(?:f|ph)ites", re.IGNORECASE)
_TABLE_WINE_RE = re.compile(r"\b(table|light)\s+(?:\w+\s+)?wine\b", re.IGNORECASE)
_ABV_ABBREV_RE = re.compile(r"\bA\.?\s?B\.?\s?V\b\.?", re.IGNORECASE)


def normalize_beverage_type(value: str | None) -> str:
    return _ALIASES.get((value or "").strip().lower(), UNSPECIFIED)


def _present(field_id: str, label: str, found: str, message: str, cite: str) -> FieldResult:
    return FieldResult(field_id, label, PASS, expected="(not in application)", found=found,
                       message=message, details=[cite])


def _missing(field_id: str, label: str, message: str, cite: str, status: str = FAIL) -> FieldResult:
    return FieldResult(field_id, label, status, expected="(not in application)", found="",
                       message=message, details=[cite])


def _abv_values(text: str) -> list[float]:
    return [_num(m.group(1)) for m in _ABV_RE.finditer(text)]


# --------------------------------------------------------------------------
# Presence checks for fields the application left blank
# --------------------------------------------------------------------------

def alcohol_presence(beverage: str, text: str) -> FieldResult | None:
    values = _abv_values(text)
    label = "Alcohol content"
    if beverage == SPIRITS:
        if values:
            return _present("alcohol_content", label, f"{values[0]:g}%",
                            "Alcohol content is stated on the label.", "Required for spirits (27 CFR 5.65).")
        return _missing("alcohol_content", label,
                        "No alcohol content as a percentage by volume. Required for distilled spirits.",
                        "27 CFR 5.65 - proof alone is not enough.")
    if beverage == WINE:
        if values:
            return _present("alcohol_content", label, f"{values[0]:g}%",
                            "Alcohol content is stated on the label.", "27 CFR 4.36")
        table = _TABLE_WINE_RE.search(text)
        if table:
            return _present("alcohol_content", label, table.group(0),
                            f'No % stated, but "{table.group(0)}" is allowed in its place for wines of 7-14%.',
                            "27 CFR 4.36(a)")
        return _missing("alcohol_content", label,
                        'No alcohol content and no "table wine" or "light wine" designation. '
                        "One is required.", "27 CFR 4.36(a)")
    if beverage == BEER:
        if values:
            return _present("alcohol_content", label, f"{values[0]:g}%",
                            "Alcohol content is stated on the label.", "27 CFR 7.65")
        return _present("alcohol_content", label, "",
                        "Not stated. Optional for malt beverages unless alcohol comes from added flavors "
                        "or State law requires it.", "27 CFR 7.63(a)(3) - confirm against the formula if flavored.")
    return None


def net_contents_presence(text: str) -> FieldResult:
    vols = parse_volumes(text)
    if vols:
        return _present("net_contents", "Net contents", f"{vols[0]:g} mL",
                        "Net contents statement found.", "Required on all alcohol beverages.")
    return _missing("net_contents", "Net contents",
                    "No net contents statement found. Required unless it's blown or embossed into the "
                    "container - check the application images.",
                    "27 CFR 4.32, 5.70, 7.70")


def name_address_presence(text: str) -> FieldResult:
    m = _NAME_ADDRESS_RE.search(text)
    if m:
        # Show the phrase plus a few words after it, so the agent sees whose name it is.
        tail = text[m.start():].split()[:8]
        return _present("bottler", "Bottler / producer", " ".join(tail),
                        "Name and address statement found.", "Required on all alcohol beverages.")
    return _missing("bottler", "Bottler / producer",
                    'No "Bottled by", "Produced by", "Imported by" (or similar) statement found.',
                    "27 CFR 4.35, 5.66-5.68, 7.66-7.68")


def country_presence(text: str) -> FieldResult | None:
    """Only applies to imports - inferred from an 'Imported by' statement on the label."""
    if not _IMPORTED_RE.search(text):
        return None
    m = _COUNTRY_RE.search(text)
    if m:
        tail = text[m.start():].split()[:5]
        return _present("country_of_origin", "Country of origin", " ".join(tail),
                        "Imported product with a country of origin statement.",
                        "Required for imports (U.S. Customs, 19 CFR 134).")
    return _missing("country_of_origin", "Country of origin",
                    'Label says "imported" but has no country of origin statement (e.g. "Product of France").',
                    "Required for imports (U.S. Customs, 19 CFR 134).")


# --------------------------------------------------------------------------
# Type-specific checks that always run
# --------------------------------------------------------------------------

def wine_checks(application: dict, text: str) -> list[FieldResult]:
    results = []
    if _SULFITES_RE.search(text):
        results.append(FieldResult("sulfites", "Sulfite declaration", PASS, found="Contains sulfites",
                                   message='"Contains sulfites" is on the label.', details=["27 CFR 4.32(e)"]))
    else:
        results.append(FieldResult("sulfites", "Sulfite declaration", REVIEW,
                                   message='No "Contains sulfites" found. Required if the wine has 10 ppm or '
                                           "more sulfur dioxide - check the application.",
                                   details=["27 CFR 4.32(e)"]))
    # A "table wine" may not exceed 14% alcohol.
    designation = clean_text(application.get("class_type", "")) + " " + text
    values = _abv_values(text) + _abv_values(application.get("alcohol_content", ""))
    if _TABLE_WINE_RE.search(designation) and any(v > 14 for v in values):
        results.append(FieldResult("wine_class", "Class vs. alcohol", FAIL,
                                   message=f"Labeled as table/light wine but alcohol is over 14% "
                                           f"({max(values):g}%). Table wine is 14% or less.",
                                   details=["27 CFR 4.21(a)"]))
    return results


def beer_checks(text: str) -> list[FieldResult]:
    for line in text.splitlines():
        if "%" in line and _ABV_ABBREV_RE.search(line):
            return [FieldResult("abv_wording", "Alcohol statement wording", FAIL, found=line.strip(),
                                message='Uses "ABV" in the alcohol statement. Malt beverage labels must '
                                        'spell it out (e.g. "Alc. 5% by Vol.").',
                                details=["27 CFR 7.65(b)"])]
    return []


def beverage_checks(beverage: str, application: dict, ocr_text: str) -> list[FieldResult]:
    """Checks for required elements, run alongside the application comparisons."""
    flat = clean_text(ocr_text)
    results: list[FieldResult] = []

    if not application.get("alcohol_content", "").strip():
        r = alcohol_presence(beverage, flat)
        if r:
            results.append(r)
    if not application.get("net_contents", "").strip():
        results.append(net_contents_presence(flat))
    if not application.get("bottler", "").strip():
        results.append(name_address_presence(flat))
    if not application.get("country_of_origin", "").strip():
        r = country_presence(flat)
        if r:
            results.append(r)

    if beverage == WINE:
        results.extend(wine_checks(application, flat))
    elif beverage == BEER:
        results.extend(beer_checks(ocr_text))  # needs line breaks
    return results
