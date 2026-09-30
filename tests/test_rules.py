"""Beverage-type requirement rules (27 CFR parts 4, 5, 7)."""

import unittest

from verifier.matching import FAIL, GOVERNMENT_WARNING, PASS, REVIEW, verify
from verifier.rules import normalize_beverage_type


def label(*lines):
    return "\n".join(lines + (GOVERNMENT_WARNING,))


def checks(application, text, beverage):
    result = verify(application, text, heading_bold=True, beverage_type=beverage)
    return result, {c["field"]: c for c in result["checks"]}


BOTTLER = "Bottled by Example Co., Louisville, KY"


class BeverageTypeTests(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(normalize_beverage_type("Distilled Spirits"), "spirits")
        self.assertEqual(normalize_beverage_type("malt beverage"), "beer")
        self.assertEqual(normalize_beverage_type(""), "unspecified")
        self.assertEqual(normalize_beverage_type("cider?"), "unspecified")


class SpiritsTests(unittest.TestCase):
    def test_missing_alcohol_fails_even_with_blank_application(self):
        result, c = checks({"brand_name": "X"}, label("X", "Gin", "750 mL", BOTTLER), "spirits")
        self.assertEqual(c["alcohol_content"]["status"], FAIL)
        self.assertEqual(result["overall"], FAIL)

    def test_proof_alone_is_not_enough(self):
        _, c = checks({"brand_name": "X"}, label("X", "Gin", "80 Proof", "750 mL", BOTTLER), "spirits")
        self.assertEqual(c["alcohol_content"]["status"], FAIL)

    def test_missing_net_contents_fails(self):
        _, c = checks({"brand_name": "X"}, label("X", "Gin", "40% Alc./Vol.", BOTTLER), "spirits")
        self.assertEqual(c["net_contents"]["status"], FAIL)

    def test_missing_name_and_address_fails(self):
        _, c = checks({"brand_name": "X"}, label("X", "Gin", "40% Alc./Vol.", "750 mL"), "spirits")
        self.assertEqual(c["bottler"]["status"], FAIL)

    def test_complete_label_passes(self):
        result, _ = checks({"brand_name": "X"}, label("X", "Gin", "40% Alc./Vol.", "750 mL", BOTTLER), "spirits")
        self.assertEqual(result["overall"], PASS)


class ImportTests(unittest.TestCase):
    def test_import_without_country_fails(self):
        _, c = checks({"brand_name": "X"},
                      label("X", "Rum", "40% Alc./Vol.", "750 mL", "Imported by X Imports, Miami, FL"), "spirits")
        self.assertEqual(c["country_of_origin"]["status"], FAIL)

    def test_import_with_country_passes(self):
        _, c = checks({"brand_name": "X"},
                      label("X", "Rum", "40% Alc./Vol.", "750 mL", "Imported by X Imports, Miami, FL",
                            "Product of Jamaica"), "spirits")
        self.assertEqual(c["country_of_origin"]["status"], PASS)

    def test_domestic_label_has_no_country_check(self):
        _, c = checks({"brand_name": "X"}, label("X", "Gin", "40% Alc./Vol.", "750 mL", BOTTLER), "spirits")
        self.assertNotIn("country_of_origin", c)


class WineTests(unittest.TestCase):
    BASE = ("X", "750 mL", "Vinted and Bottled by X Cellars, Napa, CA")

    def test_table_wine_designation_replaces_abv(self):
        result, c = checks({"brand_name": "X"}, label(*self.BASE, "Red Table Wine", "Contains Sulfites"), "wine")
        self.assertEqual(c["alcohol_content"]["status"], PASS)
        self.assertEqual(result["overall"], PASS)

    def test_no_abv_and_no_table_wine_fails(self):
        _, c = checks({"brand_name": "X"}, label(*self.BASE, "Cabernet Sauvignon", "Contains Sulfites"), "wine")
        self.assertEqual(c["alcohol_content"]["status"], FAIL)

    def test_missing_sulfites_is_review(self):
        _, c = checks({"brand_name": "X"}, label(*self.BASE, "Red Table Wine"), "wine")
        self.assertEqual(c["sulfites"]["status"], REVIEW)

    def test_table_wine_over_14_percent_fails(self):
        _, c = checks({"brand_name": "X"},
                      label(*self.BASE, "Red Table Wine", "15% Alc./Vol.", "Contains Sulfites"), "wine")
        self.assertEqual(c["wine_class"]["status"], FAIL)


class BeerTests(unittest.TestCase):
    BASE = ("X", "India Pale Ale", "12 fl oz", "Brewed by X Brewing, Asheville, NC")

    def test_alcohol_optional_for_beer(self):
        result, c = checks({"brand_name": "X"}, label(*self.BASE), "beer")
        self.assertEqual(c["alcohol_content"]["status"], PASS)
        self.assertEqual(result["overall"], PASS)

    def test_abv_abbreviation_fails(self):
        _, c = checks({"brand_name": "X"}, label(*self.BASE, "6.5% ABV"), "beer")
        self.assertEqual(c["abv_wording"]["status"], FAIL)

    def test_spelled_out_statement_ok(self):
        _, c = checks({"brand_name": "X"}, label(*self.BASE, "Alc. 6.5% by Vol."), "beer")
        self.assertNotIn("abv_wording", c)


class UnspecifiedTests(unittest.TestCase):
    def test_unspecified_skips_type_specific_alcohol_rule(self):
        _, c = checks({"brand_name": "X"}, label("X", "750 mL", BOTTLER), "")
        self.assertNotIn("alcohol_content", c)
        self.assertEqual(c["net_contents"]["status"], PASS)


if __name__ == "__main__":
    unittest.main()
