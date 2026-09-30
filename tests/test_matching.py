import unittest

from verifier.matching import (
    FAIL, GOVERNMENT_WARNING, PASS, REVIEW,
    check_alcohol_content, check_government_warning, check_net_contents,
    check_text_field, parse_volumes, verify,
)

LABEL = f"""OLD TOM DISTILLERY
Kentucky Straight
Bourbon Whiskey
45% Alc./Vol. (90 Proof)
750 mL
Distilled and Bottled by Old Tom Distillery, Bardstown, KY
{GOVERNMENT_WARNING}"""


class TextFieldTests(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(check_text_field("brand_name", "Brand", "OLD TOM DISTILLERY", LABEL).status, PASS)

    def test_case_and_punctuation_differences_pass(self):
        # Dave's example: obviously the same brand.
        r = check_text_field("brand_name", "Brand", "Stone's Throw", "STONE\u2019S THROW\nGin")
        self.assertEqual(r.status, PASS)
        self.assertTrue(r.details)  # the difference is still shown to the agent

    def test_multi_line_value_matches(self):
        r = check_text_field("class_type", "Class", "Kentucky Straight Bourbon Whiskey", LABEL)
        self.assertEqual(r.status, PASS)

    def test_ocr_noise_goes_to_review(self):
        r = check_text_field("brand_name", "Brand", "OLD TOM DISTILLERY", "OLD T0M DISTILLFRY")
        self.assertEqual(r.status, REVIEW)

    def test_different_brand_fails(self):
        r = check_text_field("brand_name", "Brand", "Northern Birch", LABEL)
        self.assertEqual(r.status, FAIL)


class AlcoholTests(unittest.TestCase):
    def test_match(self):
        self.assertEqual(check_alcohol_content("45%", LABEL).status, PASS)

    def test_decimal_match(self):
        self.assertEqual(check_alcohol_content("13.5% Alc./Vol.", "Alc. 13.5% by vol").status, PASS)

    def test_mismatch(self):
        r = check_alcohol_content("45%", "40% Alc./Vol.")
        self.assertEqual(r.status, FAIL)
        self.assertIn("40%", r.message)

    def test_inconsistent_proof_flagged(self):
        self.assertEqual(check_alcohol_content("45%", "45% Alc./Vol. (80 Proof)").status, REVIEW)

    def test_missing(self):
        self.assertEqual(check_alcohol_content("45%", "no numbers here").status, FAIL)


class NetContentsTests(unittest.TestCase):
    def test_units_convert(self):
        self.assertAlmostEqual(parse_volumes("1 L")[0], 1000)
        self.assertAlmostEqual(parse_volumes("75 cl")[0], 750)
        self.assertAlmostEqual(parse_volumes("12 FL. OZ")[0], 354.88, places=1)

    def test_equivalent_units_pass(self):
        self.assertEqual(check_net_contents("750 mL", "Contents 75cl").status, PASS)

    def test_mismatch(self):
        self.assertEqual(check_net_contents("750 mL", "1 L").status, FAIL)


class WarningTests(unittest.TestCase):
    def test_exact_warning_passes(self):
        self.assertEqual(check_government_warning(LABEL, heading_bold=True).status, PASS)

    def test_title_case_heading_fails(self):
        text = GOVERNMENT_WARNING.replace("GOVERNMENT WARNING", "Government Warning")
        r = check_government_warning(text, heading_bold=True)
        self.assertEqual(r.status, FAIL)
        self.assertIn("capitals", r.message)

    def test_reworded_warning_fails(self):
        text = GOVERNMENT_WARNING.replace("may cause health problems", "might affect your health")
        r = check_government_warning(text, heading_bold=True)
        self.assertEqual(r.status, FAIL)
        self.assertTrue(any("health" in d for d in r.details))

    def test_missing_warning_fails(self):
        self.assertEqual(check_government_warning("OLD TOM 45%").status, FAIL)

    def test_single_ocr_slip_is_review_not_fail(self):
        text = GOVERNMENT_WARNING.replace("machinery", "rnachinery")
        self.assertEqual(check_government_warning(text, heading_bold=True).status, REVIEW)

    def test_not_bold_is_review(self):
        self.assertEqual(check_government_warning(GOVERNMENT_WARNING, heading_bold=False).status, REVIEW)

    def test_line_breaks_in_warning_are_ignored(self):
        text = GOVERNMENT_WARNING.replace(" women", "\nwomen").replace(" impairs", "\nimpairs")
        self.assertEqual(check_government_warning(text, heading_bold=True).status, PASS)


class VerifyTests(unittest.TestCase):
    APP = {"brand_name": "OLD TOM DISTILLERY", "class_type": "Kentucky Straight Bourbon Whiskey",
           "alcohol_content": "45%", "net_contents": "750 mL"}

    def test_all_pass(self):
        self.assertEqual(verify(self.APP, LABEL, heading_bold=True)["overall"], PASS)

    def test_any_fail_fails(self):
        self.assertEqual(verify({**self.APP, "alcohol_content": "40%"}, LABEL, True)["overall"], FAIL)

    def test_review_without_fail(self):
        self.assertEqual(verify(self.APP, LABEL, heading_bold=False)["overall"], REVIEW)

    def test_blank_field_becomes_presence_check(self):
        checks = {c["field"]: c for c in verify({**self.APP, "bottler": ""}, LABEL, True)["checks"]}
        self.assertEqual(checks["bottler"]["status"], PASS)
        self.assertEqual(checks["bottler"]["expected"], "(not in application)")
        self.assertIn("government_warning", checks)  # always checked


if __name__ == "__main__":
    unittest.main()
