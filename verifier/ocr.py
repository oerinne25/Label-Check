"""Read text from a label image, locally, with Tesseract.

Why local OCR instead of a cloud vision API: the agency firewall blocks many
outbound ML endpoints (that's what sank the last vendor pilot), and label
artwork shouldn't leave the network. Tesseract runs on the same box as the
app, needs no API key, and reads a typical label in 1-3 seconds.

Preprocessing targets the photos Jenny described: odd angles, poor lighting,
glare. It is deliberately cheap so the whole request stays under ~5 seconds.
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

MIN_WIDTH, MAX_WIDTH = 1000, 2400  # px; resize only outside this range (resizing clean images hurts OCR)
MIN_WORDS_BEFORE_RETRY = 15  # fewer words than this -> try rotating the image
BOLD_RATIO = 1.18            # heading stroke width / body stroke width to call it bold


@dataclass
class OcrResult:
    text: str
    mean_confidence: float
    heading_bold: bool | None
    seconds: float
    notes: list[str]


class UnreadableImage(ValueError):
    """Raised when the upload isn't an image we can open."""


def load_image(data: bytes) -> np.ndarray:
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img)  # phone photos store rotation in EXIF
        img = img.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same to the user
        raise UnreadableImage("This file isn't an image we can open. Use JPG, PNG, or WebP.") from exc
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)


def preprocess(gray: np.ndarray) -> np.ndarray:
    # Upscale small images so fine print is legible; shrink huge phone photos for speed.
    h, w = gray.shape
    if w < MIN_WIDTH or w > MAX_WIDTH:
        target = 1400 if w < MIN_WIDTH else 2000
        interp = cv2.INTER_CUBIC if target > w else cv2.INTER_AREA
        gray = cv2.resize(gray, (target, int(h * target / w)), interpolation=interp)
    # Even out lighting and soften glare with local contrast equalisation.
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    # Light denoise that keeps letter edges.
    gray = cv2.bilateralFilter(gray, 5, 40, 40)
    return deskew(gray)


def _profile_score(bw: np.ndarray, angle: float) -> float:
    """How 'line-like' the text is at this rotation: sharp row-sum peaks = straight lines."""
    h, w = bw.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rows = cv2.warpAffine(bw, m, (w, h)).sum(axis=1, dtype=np.float64)
    return float(np.var(np.diff(rows)))


def deskew(gray: np.ndarray) -> np.ndarray:
    """Straighten tilts up to 15 degrees by finding the angle where text rows line up best.

    Searched on a small copy of the image (coarse 1-degree steps, then 0.25-degree
    refinement) so it costs ~100 ms.
    """
    small = cv2.resize(gray, (500, int(500 * gray.shape[0] / gray.shape[1])), interpolation=cv2.INTER_AREA)
    bw = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 25, 15)
    coarse = max(range(-15, 16), key=lambda a: _profile_score(bw, a))
    fine = max(np.arange(coarse - 1, coarse + 1.01, 0.25), key=lambda a: _profile_score(bw, a))
    if abs(fine) < 0.5:
        return gray
    h, w = gray.shape
    m = cv2.getRotationMatrix2D((w / 2, h / 2), float(fine), 1.0)
    return cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _run_tesseract(img: np.ndarray) -> dict:
    # psm 11 = sparse text: labels are scattered blocks, not a page of prose.
    return pytesseract.image_to_data(img, config="--oem 1 --psm 11", output_type=pytesseract.Output.DICT)


def _words(data: dict) -> list[dict]:
    out = []
    for i, word in enumerate(data["text"]):
        if word.strip() and float(data["conf"][i]) >= 0:
            out.append({
                "text": word, "conf": float(data["conf"][i]),
                "box": (data["left"][i], data["top"][i], data["width"][i], data["height"][i]),
                "line": (data["block_num"][i], data["par_num"][i], data["line_num"][i]),
            })
    return out


def _join(words: list[dict]) -> str:
    lines, current, key = [], [], None
    for w in words:
        if key is not None and w["line"] != key:
            lines.append(" ".join(current))
            current = []
        current.append(w["text"])
        key = w["line"]
    if current:
        lines.append(" ".join(current))
    return "\n".join(lines)


def _stroke_width(img: np.ndarray, box: tuple[int, int, int, int]) -> float | None:
    """Average stroke thickness of the ink in a box: 2 * ink area / ink perimeter."""
    x, y, w, h = box
    crop = img[max(0, y):y + h, max(0, x):x + w]
    if crop.size == 0 or h < 6:
        return None
    _, bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(bw, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    perimeter = sum(cv2.arcLength(c, True) for c in contours)
    area = float(np.count_nonzero(bw))
    return 2 * area / perimeter if perimeter > 0 else None


def heading_is_bold(img: np.ndarray, words: list[dict]) -> bool | None:
    """Compare stroke width of 'GOVERNMENT WARNING:' against the warning body text."""
    for i in range(len(words) - 1):
        if re.fullmatch(r"GOVERNMENT", words[i]["text"]) and words[i + 1]["text"].upper().startswith("WARNING"):
            head = [_stroke_width(img, words[j]["box"]) for j in (i, i + 1)]
            body = [_stroke_width(img, w["box"]) for w in words[i + 2:i + 14] if len(w["text"]) >= 4]
            head = [v for v in head if v]
            body = [v for v in body if v]
            if not head or len(body) < 3:
                return None
            return float(np.mean(head)) / float(np.median(body)) >= BOLD_RATIO
    return None


def read_label(data: bytes) -> OcrResult:
    started = time.perf_counter()
    notes: list[str] = []
    img = preprocess(load_image(data))
    words = _words(_run_tesseract(img))

    # Sideways or upside-down photo? Try the other orientations once.
    if len(words) < MIN_WORDS_BEFORE_RETRY:
        for code, label in ((cv2.ROTATE_90_CLOCKWISE, "90"), (cv2.ROTATE_180, "180"),
                            (cv2.ROTATE_90_COUNTERCLOCKWISE, "270")):
            rotated = cv2.rotate(img, code)
            candidate = _words(_run_tesseract(rotated))
            if len(candidate) > len(words) * 1.5 and len(candidate) >= MIN_WORDS_BEFORE_RETRY:
                img, words = rotated, candidate
                notes.append(f"Image was rotated {label} degrees to read it.")
                break

    confs = [w["conf"] for w in words]
    mean_conf = float(np.mean(confs)) if confs else 0.0
    if not words:
        notes.append("No readable text found. The image may be blurry, too dark, or not a label.")
    elif mean_conf < 60:
        notes.append("Parts of this image were hard to read. Results marked for review may be reading errors.")

    return OcrResult(
        text=_join(words),
        mean_confidence=round(mean_conf, 1),
        heading_bold=heading_is_bold(img, words),
        seconds=round(time.perf_counter() - started, 2),
        notes=notes,
    )
