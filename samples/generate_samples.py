"""Generate test labels + a matching batch CSV.

Each label exercises one scenario from the stakeholder interviews.
Run:  python samples/generate_samples.py   ->  samples/output/
"""

from __future__ import annotations

import csv
import random
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "output"
FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/truetype/liberation"),
             Path("C:/Windows/Fonts"), Path("/Library/Fonts")]

WARNING_BODY = ("(1) According to the Surgeon General, women should not drink alcoholic beverages "
                "during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic "
                "beverages impairs your ability to drive a car or operate machinery, and may cause "
                "health problems.")


def font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for d in FONT_DIRS:
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    return ImageFont.load_default(size)


SERIF_BOLD = ["DejaVuSerif-Bold.ttf", "LiberationSerif-Bold.ttf", "timesbd.ttf"]
SERIF = ["DejaVuSerif.ttf", "LiberationSerif-Regular.ttf", "times.ttf"]
SANS = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "arial.ttf"]
SANS_BOLD = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "arialbd.ttf"]


def centered(draw, y, text, f, fill, width):
    w = draw.textlength(text, font=f)
    draw.text(((width - w) / 2, y), text, font=f, fill=fill)
    return y + f.size * 1.3


def warning_block(draw, x, y, max_w, heading, body, heading_bold=True, size=22):
    """Lay out heading + body as flowing words with mixed fonts."""
    hf = font(SANS_BOLD if heading_bold else SANS, size)
    bf = font(SANS, size)
    tokens = [(w, hf) for w in heading.split()] + [(w, bf) for w in body.split()]
    cx, line_h = x, size * 1.35
    for word, f in tokens:
        ww = draw.textlength(word + " ", font=f)
        if cx + ww > x + max_w:
            cx, y = x, y + line_h
        draw.text((cx, y), word, font=f, fill="#1a1a1a")
        cx += ww
    return y + line_h


def make_label(spec: dict) -> Image.Image:
    W, H = 1000, 1350
    img = Image.new("RGB", (W, H), spec.get("bg", "#f3ead7"))
    d = ImageDraw.Draw(img)
    ink = spec.get("ink", "#2b1d12")
    d.rectangle([30, 30, W - 30, H - 30], outline=ink, width=6)
    d.rectangle([48, 48, W - 48, H - 48], outline=ink, width=2)

    y = 130
    brand_font = font(SERIF_BOLD, 76)
    while d.textlength(spec["brand"], font=brand_font) > W - 220:  # keep clear of the border
        brand_font = font(SERIF_BOLD, brand_font.size - 4)
    y = centered(d, y, spec["brand"], brand_font, ink, W) + 20
    for line in spec["class_lines"]:
        y = centered(d, y, line, font(SERIF, 44), ink, W)
    y += 50
    if spec.get("abv"):
        y = centered(d, y, spec["abv"], font(SANS_BOLD, 40), ink, W)
    if spec.get("net"):
        y = centered(d, y, spec["net"], font(SANS, 38), ink, W)
    y += 40
    for line in spec["bottler"]:
        y = centered(d, y, line, font(SANS, 26), ink, W)
    if spec.get("country"):
        y = centered(d, y, spec["country"], font(SANS, 26), ink, W)
    for line in spec.get("extra", []):
        y = centered(d, y + 10, line, font(SANS_BOLD, 26), ink, W)

    if spec.get("warning", True):
        warning_block(d, 90, H - 340, W - 180, spec.get("heading", "GOVERNMENT WARNING:"),
                      spec.get("body", WARNING_BODY), spec.get("heading_bold", True))
    return img


def bad_photo(img: Image.Image, angle: float, seed: int = 7) -> Image.Image:
    """Simulate a phone snap: tilt, uneven light, a glare spot, blur, JPEG."""
    random.seed(seed)
    bg = Image.new("RGB", (img.width + 300, img.height + 300), "#5b5f63")
    bg.paste(img, (150, 150))
    img = bg.rotate(angle, resample=Image.BICUBIC, fillcolor="#5b5f63")
    shade = Image.linear_gradient("L").resize(img.size).rotate(90)
    img = Image.composite(img, Image.new("RGB", img.size, "#6d6356"),
                          shade.point(lambda p: 150 + p * 105 // 255))
    glare = Image.new("L", img.size, 0)
    ImageDraw.Draw(glare).ellipse([img.width * 0.62, img.height * 0.18,
                                   img.width * 0.84, img.height * 0.32], fill=150)
    glare = glare.filter(ImageFilter.GaussianBlur(60))
    img = Image.composite(Image.new("RGB", img.size, "white"), img, glare)
    return img.filter(ImageFilter.GaussianBlur(0.8))


OLD_TOM = dict(brand="OLD TOM DISTILLERY", class_lines=["Kentucky Straight", "Bourbon Whiskey"],
               abv="45% Alc./Vol. (90 Proof)", net="750 mL",
               bottler=["Distilled and Bottled by", "Old Tom Distillery, Bardstown, KY"])
OLD_TOM_APP = dict(beverage_type="spirits", brand_name="OLD TOM DISTILLERY", class_type="Kentucky Straight Bourbon Whiskey",
                   alcohol_content="45% Alc./Vol. (90 Proof)", net_contents="750 mL",
                   bottler="Old Tom Distillery, Bardstown, KY", country_of_origin="")

SAMPLES = [
    # filename, label spec, application values (incl. beverage_type), expected result, what it demonstrates
    ("01_old_tom_compliant.png", OLD_TOM, OLD_TOM_APP, "pass",
     "The sample label from the brief. Everything matches."),
    ("02_stones_throw_case.png",
     dict(brand="STONE'S THROW", class_lines=["London Dry Gin"], abv="41.2% Alc./Vol.", net="1 L",
          bottler=["Bottled by Stone's Throw Spirits", "Portland, OR"], bg="#e6eef0", ink="#16324a"),
     dict(beverage_type="spirits", brand_name="Stone's Throw", class_type="London Dry Gin", alcohol_content="41.2%",
          net_contents="1 L", bottler="", country_of_origin=""), "pass",
     "Dave's case: label says STONE'S THROW, application says Stone's Throw. Treated as a match."),
    ("03_vodka_wrong_abv.png",
     dict(brand="NORTHERN BIRCH", class_lines=["Vodka"], abv="40% Alc./Vol. (80 Proof)", net="750 mL",
          bottler=["Produced by Northern Birch Co.", "Duluth, MN"], bg="#eeeeee", ink="#1f2a36"),
     dict(beverage_type="spirits", brand_name="Northern Birch", class_type="Vodka", alcohol_content="45% Alc./Vol.",
          net_contents="750 mL", bottler="", country_of_origin=""), "fail",
     "Application says 45%, label says 40%."),
    ("04_rum_titlecase_warning.png",
     dict(brand="CAYO AZUL", class_lines=["Aged Rum"], abv="40% Alc./Vol.", net="750 mL",
          bottler=["Imported by Cayo Azul Imports, Miami, FL"], country="Product of Dominican Republic",
          heading="Government Warning:", bg="#f4e8d2", ink="#3a2410"),
     dict(beverage_type="spirits", brand_name="Cayo Azul", class_type="Aged Rum", alcohol_content="40%", net_contents="750 mL",
          bottler="", country_of_origin="Dominican Republic"), "fail",
     "Jenny's case: warning heading in title case instead of capitals."),
    ("05_wine_reworded_warning.png",
     dict(brand="HOLLOW OAK", class_lines=["Napa Valley", "Cabernet Sauvignon"], abv="13.5% Alc./Vol.",
          net="750 mL", bottler=["Vinted and Bottled by Hollow Oak Cellars", "Napa, CA"],
          body=WARNING_BODY.replace("women should not drink", "pregnant women should avoid drinking"),
          extra=["CONTAINS SULFITES"],
          bg="#f2e9e4", ink="#4a1220"),
     dict(beverage_type="wine", brand_name="Hollow Oak", class_type="Cabernet Sauvignon", alcohol_content="13.5%",
          net_contents="750 mL", bottler="", country_of_origin=""), "fail",
     "Warning statement reworded - must be word-for-word."),
    ("06_old_tom_bad_photo.jpg", OLD_TOM, OLD_TOM_APP, "pass or review",
     "Same compliant label, photographed at an angle with uneven light and glare."),
    ("07_ipa_no_warning.png",
     dict(brand="RIVERBEND BREWING", class_lines=["India Pale Ale"], abv="6.8% Alc./Vol.",
          net="12 fl oz", bottler=["Brewed by Riverbend Brewing Co.", "Asheville, NC"], warning=False,
          bg="#fbf3dc", ink="#233d1f"),
     dict(beverage_type="beer", brand_name="Riverbend Brewing", class_type="India Pale Ale", alcohol_content="6.8%",
          net_contents="12 fl oz", bottler="", country_of_origin=""), "fail",
     "No government warning on the label."),
    ("08_bourbon_heading_not_bold.png", dict(OLD_TOM, heading_bold=False), OLD_TOM_APP, "review",
     "Warning wording is right, but the heading isn't bold. Flagged for a human."),
    ("09_table_wine_no_abv.png",
     dict(brand="MESA VERDE", class_lines=["Red Table Wine"], abv=None, net="750 mL",
          bottler=["Cellared and Bottled by Mesa Verde Winery", "Paso Robles, CA"], extra=["CONTAINS SULFITES"],
          bg="#f1e6e9", ink="#4b1426"),
     dict(beverage_type="wine", brand_name="Mesa Verde", class_type="Red Table Wine", alcohol_content="",
          net_contents="750 mL", bottler="", country_of_origin=""), "pass",
     'Wine with no % stated: allowed because "Table Wine" is the designation (27 CFR 4.36).'),
    ("10_lager_abv_abbreviation.png",
     dict(brand="HARBOR LIGHT", class_lines=["Lager"], abv="4.8% ABV", net="12 fl oz",
          bottler=["Brewed and Canned by Harbor Light Brewing", "Portland, ME"], bg="#e9f0f6", ink="#15314d"),
     dict(beverage_type="beer", brand_name="Harbor Light", class_type="Lager", alcohol_content="4.8%",
          net_contents="12 fl oz", bottler="", country_of_origin=""), "fail",
     'Beer label uses "ABV", which TTB doesn\'t allow in the alcohol statement (27 CFR 7.65).'),
    ("11_gin_missing_net_contents.png",
     dict(brand="COPPER FOX", class_lines=["American Dry Gin"], abv="44% Alc./Vol. (88 Proof)", net=None,
          bottler=["Distilled and Bottled by Copper Fox Spirits", "Austin, TX"], bg="#eef1e8", ink="#233322"),
     dict(beverage_type="spirits", brand_name="Copper Fox", class_type="American Dry Gin",
          alcohol_content="44%", net_contents="", bottler="", country_of_origin=""), "fail",
     "No net contents on the label. The application field was blank too, but it's still required."),
    ("12_tequila_import_no_country.png",
     dict(brand="SOL DE AGAVE", class_lines=["Tequila Blanco"], abv="40% Alc./Vol. (80 Proof)", net="750 mL",
          bottler=["Imported by Agave Trade Co.", "San Diego, CA"], bg="#f5efe0", ink="#3d2a0e"),
     dict(beverage_type="spirits", brand_name="Sol de Agave", class_type="Tequila Blanco",
          alcohol_content="40%", net_contents="750 mL", bottler="", country_of_origin=""), "fail",
     "Imported, but no country of origin statement on the label."),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, spec, app, expected, why in SAMPLES:
        img = make_label(spec)
        if "bad_photo" in name:
            img = bad_photo(img, angle=8)
            img.save(OUT / name, quality=80)
        else:
            img.save(OUT / name)
        rows.append({"filename": name, **app, "expected_result": expected, "scenario": why})
    with open(OUT / "applications.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    # One zip with everything, so testers can try batch mode in two clicks.
    with zipfile.ZipFile(OUT / "sample_labels.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for row in rows:
            z.write(OUT / row["filename"], row["filename"])
        z.write(OUT / "applications.csv", "applications.csv")
    print(f"Wrote {len(rows)} labels, applications.csv and sample_labels.zip to {OUT}")


if __name__ == "__main__":
    main()
