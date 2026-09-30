"""Rules that compare application data against text read from a label.

Every check returns a FieldResult with one of three statuses:

  PASS    - the label agrees with the application
  REVIEW  - probably fine, but a human should glance at it
            (e.g. OCR was unsure, or the difference is cosmetic)
  FAIL    - the label clearly disagrees with the application

The tool never has the last word: REVIEW exists so that agents keep the
judgment calls (Dave's "STONE'S THROW" vs "Stone's Throw" case) while the
routine matching is automated.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher

PASS, REVIEW, FAIL = "pass", "review", "fail"

# 27 CFR 16.21 - the mandatory health warning, word for word.
GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)
WARNING_HEADING = "GOVERNMENT WARNING:"

# Similarity thresholds for free-text fields (brand, class/type, bottler...).
# Above STRONG we accept small OCR noise; between WEAK and STRONG a human decides.
STRONG_MATCH = 0.90
WEAK_MATCH = 0.75


@dataclass
class FieldResult:
    field: str
    label: str              # human-readable field name
    status: str
    expected: str = ""      # what the application says
    found: str = ""         # what we read on the label
    message: str = ""       # plain-English explanation for the agent
    details: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# Text normalisation helpers
# --------------------------------------------------------------------------

_QUOTES = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "`": "'"}


def clean_text(text: str) -> str:
    """Unicode-normalise, unify quotes/dashes, collapse whitespace. Keeps case."""
    text = unicodedata.normalize("NFKC", text or "")
    for bad, good in _QUOTES.items():
        text = text.replace(bad, good)
    text = re.sub(r"[\u2010-\u2015]", "-", text)
    return re.sub(r"\s+", " ", text).strip()


def loose_key(text: str) -> str:
    """Case- and punctuation-insensitive form used for 'same thing?' checks."""
    text = clean_text(text).casefold()
    text = re.sub(r"[^\w%. ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


def best_window_match(needle: str, haystack: str) -> tuple[float, str]:
    """Find the span of `haystack` most similar to `needle`.

    Compares against every run of words the same length as the needle
    (plus or minus one word, to tolerate OCR splitting/merging words).
    Returns (similarity 0..1, matched text in the haystack's original form).
    """
    n_words = needle.split()
    h_words = haystack.split()
    if not n_words or not h_words:
        return 0.0, ""
    target = " ".join(loose_key(w) for w in n_words)
    best = (0.0, "")
    for size in {max(1, len(n_words) - 1), len(n_words), len(n_words) + 1}:
        for i in range(0, max(1, len(h_words) - size + 1)):
            window = h_words[i:i + size]
            score = _similarity(target, " ".join(loose_key(w) for w in window))
            if score > best[0]:
                best = (score, " ".join(window))
    return best


# --------------------------------------------------------------------------
# Individual field checks
# --------------------------------------------------------------------------

def check_text_field(field_id: str, label: str, expected: str, ocr_text: str) -> FieldResult:
    """Brand name, class/type, bottler, country: judgment-friendly matching."""
    expected_clean = clean_text(expected)
    result = FieldResult(field_id, label, FAIL, expected=expected_clean)

    # 1. Exact, character-for-character.
    if expected_clean and expected_clean in clean_text(ocr_text):
        result.status, result.found = PASS, expected_clean
        result.message = "Exact match on the label."
        return result

    # 2. Same words, different capitalisation/punctuation - obviously the same.
    score, found = best_window_match(expected_clean, clean_text(ocr_text))
    found = found.strip(" ,;:")
    result.found = found
    if loose_key(found) == loose_key(expected_clean):
        result.status = PASS
        result.message = "Matches, ignoring capitalisation and punctuation."
        if found != expected_clean:
            result.details.append(f'Label shows "{found}", application shows "{expected_clean}".')
        return result

    # 3. Close enough that the difference is probably OCR noise.
    if score >= STRONG_MATCH:
        result.status = REVIEW
        result.message = f"Very close match ({score:.0%}). Likely a reading error - confirm by eye."
    elif score >= WEAK_MATCH:
        result.status = REVIEW
        result.message = f"Partial match ({score:.0%}). Check the label by eye."
    else:
        result.status = FAIL
        result.message = "Not found on the label."
        if score > 0.4 and found:
            result.details.append(f'Closest text on the label: "{found}".')
    return result


_ABV_RE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")
_PROOF_RE = re.compile(r"(\d{1,3}(?:[.,]\d)?)\s*[- ]?\s*proof", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def check_alcohol_content(expected: str, ocr_text: str) -> FieldResult:
    result = FieldResult("alcohol_content", "Alcohol content", FAIL, expected=clean_text(expected))
    exp_abv = _ABV_RE.search(expected or "")
    if not exp_abv:
        result.status = REVIEW
        result.message = "Couldn't read a percentage in the application value."
        return result
    target = _num(exp_abv.group(1))

    text = clean_text(ocr_text)
    found = [_num(m.group(1)) for m in _ABV_RE.finditer(text)]
    proofs = [_num(m.group(1)) for m in _PROOF_RE.finditer(text)]

    if target in found:
        result.status, result.found = PASS, f"{target:g}%"
        result.message = "Alcohol content matches."
        # Cross-check proof if the label states one (US proof = 2 x ABV).
        if proofs and not any(abs(p - 2 * target) < 0.6 for p in proofs):
            result.status = REVIEW
            result.message = "ABV matches, but the proof on the label doesn't equal 2 x ABV."
            result.details.append(f"Proof on label: {', '.join(f'{p:g}' for p in proofs)}")
        return result

    if found:
        result.found = ", ".join(f"{v:g}%" for v in found)
        result.message = f"Label shows {result.found}, application says {target:g}%."
    elif proofs and any(abs(p - 2 * target) < 0.6 for p in proofs):
        result.status = REVIEW
        result.found = f"{proofs[0]:g} proof"
        result.message = "Proof matches, but the % figure couldn't be read. Confirm by eye."
    else:
        result.message = "No alcohol percentage found on the label."
    return result


# unit -> millilitres
_UNITS = {
    "ml": 1.0, "milliliter": 1.0, "milliliters": 1.0, "millilitre": 1.0, "millilitres": 1.0,
    "cl": 10.0, "l": 1000.0, "liter": 1000.0, "liters": 1000.0, "litre": 1000.0, "litres": 1000.0,
    "fl oz": 29.5735, "fl. oz": 29.5735, "fl.oz": 29.5735, "oz": 29.5735,
}
_VOLUME_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(fl\.?\s*oz|millilit(?:er|re)s?|lit(?:er|re)s?|ml|cl|l)\b",
    re.IGNORECASE,
)


def parse_volumes(text: str) -> list[float]:
    vols = []
    for m in _VOLUME_RE.finditer(clean_text(text)):
        unit = re.sub(r"\s+", " ", m.group(2).lower()).replace("fl. oz", "fl oz").replace("fl.oz", "fl oz")
        vols.append(_num(m.group(1)) * _UNITS.get(unit, 1.0))
    return vols


def check_net_contents(expected: str, ocr_text: str) -> FieldResult:
    result = FieldResult("net_contents", "Net contents", FAIL, expected=clean_text(expected))
    exp = parse_volumes(expected)
    if not exp:
        result.status = REVIEW
        result.message = "Couldn't read a volume in the application value."
        return result
    found = parse_volumes(ocr_text)
    # 1% tolerance handles "750 mL" vs "25.4 fl oz" style dual statements.
    if any(abs(v - exp[0]) <= exp[0] * 0.01 for v in found):
        result.status, result.found = PASS, result.expected
        result.message = "Net contents match."
    elif found:
        result.found = ", ".join(f"{v:g} mL" for v in found)
        result.message = f"Label shows {result.found}, application says {exp[0]:g} mL."
    else:
        result.message = "No net contents statement found on the label."
    return result


def _word_diff(expected: str, found: str) -> list[str]:
    """Plain-English list of word-level differences, for the agent."""
    e, f = expected.split(), found.split()
    notes = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, e, f, autojunk=False).get_opcodes():
        if op == "replace":
            notes.append(f'Expected "{" ".join(e[i1:i2])}" but label has "{" ".join(f[j1:j2])}"')
        elif op == "delete":
            notes.append(f'Missing: "{" ".join(e[i1:i2])}"')
        elif op == "insert":
            notes.append(f'Extra text: "{" ".join(f[j1:j2])}"')
    return notes[:6]


def check_government_warning(ocr_text: str, heading_bold: bool | None = None) -> FieldResult:
    """Strict check: heading in capitals, statement word-for-word.

    `heading_bold` comes from the image analysis in ocr.py:
    True = heading measured as heavier than body text, False = not heavier,
    None = couldn't measure. Bold is never auto-failed because pixel
    heuristics aren't reliable enough to reject an application on.
    """
    result = FieldResult("government_warning", "Government warning", FAIL, expected=GOVERNMENT_WARNING)
    text = clean_text(ocr_text)

    start = re.search(r"government\s+warning\s*:?", text, re.IGNORECASE)
    if not start:
        # Maybe the heading was mangled but the body is there.
        score, found = best_window_match(GOVERNMENT_WARNING, text)
        result.found = found if score > 0.5 else ""
        result.message = "Government warning not found on the label."
        if score > 0.5:
            result.details.append(f"Closest text found ({score:.0%} similar): \"{found[:120]}...\"")
        return result

    # Take roughly the warning's length of text starting at the heading.
    tail_words = text[start.start():].split()
    candidate = " ".join(tail_words[: len(GOVERNMENT_WARNING.split()) + 3])
    _, found = best_window_match(GOVERNMENT_WARNING, candidate)
    result.found = found

    heading = start.group(0)
    if not heading.startswith("GOVERNMENT WARNING"):
        result.message = f'Heading must be in capitals: label shows "{heading.strip()}".'
        return result

    if found == GOVERNMENT_WARNING:
        body_ok = PASS
    else:
        # Distinguish OCR noise (a letter or two) from reworded text.
        diffs = _word_diff(GOVERNMENT_WARNING, found)
        char_score = _similarity(GOVERNMENT_WARNING, found)
        body_ok = REVIEW if char_score >= 0.97 else FAIL
        result.details.extend(diffs)

    if body_ok == FAIL:
        result.message = "Warning text doesn't match the required wording."
        return result

    if body_ok == REVIEW:
        result.status = REVIEW
        result.message = "Warning is nearly exact. The differences may be reading errors - confirm by eye."
    else:
        result.status = PASS
        result.message = "Warning text is word-for-word correct and the heading is in capitals."

    if heading_bold is False:
        result.status = REVIEW
        result.message = "Wording and capitals are correct, but the heading may not be bold."
        result.details.append('"GOVERNMENT WARNING:" doesn\'t appear bolder than the rest of the text. Check by eye.')
    elif heading_bold is None:
        result.details.append("Bold heading couldn't be measured automatically. Check by eye.")
    return result


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

# Application fields the UI/CSV can supply, in display order.
TEXT_FIELDS = {
    "brand_name": "Brand name",
    "class_type": "Class / type",
    "bottler": "Bottler / producer",
    "country_of_origin": "Country of origin",
}


# Display order for the checklist.
FIELD_ORDER = ["brand_name", "class_type", "alcohol_content", "abv_wording", "wine_class", "net_contents",
               "bottler", "country_of_origin", "sulfites", "government_warning"]


def verify(application: dict, ocr_text: str, heading_bold: bool | None = None,
           beverage_type: str = "unspecified") -> dict:
    """Run every applicable check and roll up an overall verdict.

    Two kinds of check run together:
      - comparisons: application value vs. label (for fields the application supplies)
      - requirements: elements TTB requires for this beverage type (rules.py), which
        catch a missing element even when the application field was left blank.
    """
    from .rules import BEVERAGE_LABELS, beverage_checks, normalize_beverage_type  # avoid import cycle

    beverage = normalize_beverage_type(beverage_type)
    checks: list[FieldResult] = []
    for key in ("brand_name", "class_type", "bottler", "country_of_origin"):
        if application.get(key, "").strip():
            checks.append(check_text_field(key, TEXT_FIELDS[key], application[key], ocr_text))
    if application.get("alcohol_content", "").strip():
        checks.append(check_alcohol_content(application["alcohol_content"], ocr_text))
    if application.get("net_contents", "").strip():
        checks.append(check_net_contents(application["net_contents"], ocr_text))
    checks.extend(beverage_checks(beverage, application, ocr_text))
    # The warning is mandatory on every label, so it is always checked.
    checks.append(check_government_warning(ocr_text, heading_bold))
    checks.sort(key=lambda c: FIELD_ORDER.index(c.field) if c.field in FIELD_ORDER else len(FIELD_ORDER))

    statuses = {c.status for c in checks}
    overall = FAIL if FAIL in statuses else REVIEW if REVIEW in statuses else PASS
    return {"overall": overall, "beverage_type": beverage,
            "beverage_label": BEVERAGE_LABELS[beverage], "checks": [c.to_dict() for c in checks]}
