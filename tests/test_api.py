"""End-to-end: real OCR on every generated sample label, through the HTTP API."""

import csv
import io
import unittest
from pathlib import Path

from app import app

SAMPLES = Path(__file__).resolve().parent.parent / "samples" / "output"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (SAMPLES / "applications.csv").exists():
            from samples.generate_samples import main
            main()
        cls.client = app.test_client()

    def post(self, filename, fields):
        with open(SAMPLES / filename, "rb") as f:
            data = {"image": (io.BytesIO(f.read()), filename), **fields}
        return self.client.post("/api/verify", data=data, content_type="multipart/form-data")

    def test_every_sample_gets_expected_verdict_within_5_seconds(self):
        with open(SAMPLES / "applications.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        for row in rows:
            with self.subTest(label=row["filename"]):
                res = self.post(row["filename"], row)
                self.assertEqual(res.status_code, 200)
                body = res.get_json()
                self.assertIn(body["overall"], row["expected_result"])
                self.assertLess(body["seconds"], 5)

    def test_missing_image(self):
        res = self.client.post("/api/verify", data={"brand_name": "X"})
        self.assertEqual(res.status_code, 400)

    def test_missing_application_values(self):
        res = self.post("01_old_tom_compliant.png", {})
        self.assertEqual(res.status_code, 400)

    def test_non_image_rejected(self):
        data = {"image": (io.BytesIO(b"hello"), "notes.txt", "text/plain"), "brand_name": "X"}
        res = self.client.post("/api/verify", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 415)

    def test_corrupt_image(self):
        data = {"image": (io.BytesIO(b"not really a png"), "bad.png", "image/png"), "brand_name": "X"}
        res = self.client.post("/api/verify", data=data, content_type="multipart/form-data")
        self.assertEqual(res.status_code, 422)
        self.assertIn("error", res.get_json())


if __name__ == "__main__":
    unittest.main()
