"""Label Check - web server.

One API endpoint does the work: POST /api/verify with a label image and the
application's values. Batch mode in the browser calls the same endpoint for
each label, a few at a time, so results appear as they finish and a 300-label
upload never hits a request timeout.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from verifier.matching import verify
from verifier.ocr import UnreadableImage, read_label

BASE = Path(__file__).parent
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp"}
APPLICATION_FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents",
                      "bottler", "country_of_origin")

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024  # 15 MB per label
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("label-check")


def error(message: str, status: int):
    return jsonify({"error": message}), status


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/samples/<path:name>")
def samples(name: str):
    return send_from_directory(BASE / "samples" / "output", name)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/verify")
def api_verify():
    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return error("Add a label image to check.", 400)
    if upload.mimetype not in ALLOWED_TYPES:
        return error(f'"{upload.filename}" isn\'t a supported image. Use JPG, PNG, or WebP.', 415)

    application = {k: request.form.get(k, "").strip() for k in APPLICATION_FIELDS}
    if not any(application[k] for k in ("brand_name", "class_type", "alcohol_content", "net_contents")):
        return error("Enter at least one value from the application to compare against.", 400)

    try:
        ocr = read_label(upload.read())
    except UnreadableImage as exc:
        return error(str(exc), 422)

    result = verify(application, ocr.text, ocr.heading_bold, request.form.get("beverage_type", ""))
    result.update({
        "filename": upload.filename,
        "ocr_text": ocr.text,
        "ocr_confidence": ocr.mean_confidence,
        "seconds": ocr.seconds,
        "notes": ocr.notes,
    })
    # Log outcome only - no label text or application data (nothing sensitive is retained).
    log.info("verified file=%s overall=%s seconds=%.2f", upload.filename, result["overall"], ocr.seconds)
    return jsonify(result)


@app.errorhandler(RequestEntityTooLarge)
def too_large(_):
    return error("That image is over 15 MB. Save it as a smaller JPG and try again.", 413)


@app.errorhandler(Exception)
def unexpected(exc):
    if isinstance(exc, HTTPException):
        return error(exc.description, exc.code)
    log.exception("Unhandled error")
    return error("Something went wrong reading this label. Try again, or check it by hand.", 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
