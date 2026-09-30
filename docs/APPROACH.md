# Approach, tools, and assumptions

## How the stakeholder interviews shaped the design

| What we heard | Decision |
|---|---|
| **Sarah:** results in ~5 seconds or nobody uses it | Local OCR, cheap preprocessing, no network round-trips. Typical label: ~1 s; under 3 s with four running at once on one CPU core. An automated test fails if any sample takes 5 s or more. |
| **Marcus:** firewall blocks outbound ML endpoints | No cloud AI APIs. Tesseract runs inside the container. The front end loads nothing from external sites (no CDNs, no web fonts). |
| **Sarah:** usable by a 73-year-old; half the team is over 50 | 18 px base text, large buttons, two plain tabs, one primary action per screen. Results are a checklist with ✓ / ! / ✕, a status word, and a colour, so meaning never depends on colour alone. Errors say what happened and what to do next. |
| **Sarah / Janet:** importers send 200–300 labels at once | Batch mode: images + one CSV. The browser sends labels four at a time to the same endpoint, so results appear as they finish, there is no long-running request to time out, and the agent can stop at any point. Failures sort to the top. Results export to CSV. |
| **Dave:** `STONE'S THROW` vs `Stone's Throw` needs judgment | Free-text fields match ignoring case and punctuation, and the difference is still shown. Near-matches go to **Needs review**, not Fail. |
| **Jenny:** warning must be exact, heading in capitals and bold | The warning is compared word for word against 27 CFR 16.21. A title-case heading fails. Reworded text fails, with the differences listed. Bold is measured from the image (see below). |
| **Jenny:** angled photos, bad lighting, glare | EXIF rotation, local contrast equalisation (CLAHE), automatic straightening of tilts up to 15°, and retrying sideways/upside-down orientations. |
| **Brief:** requirements vary by beverage type; review ttb.gov | Product-type selector with rules taken from TTB's published requirements (27 CFR parts 4, 5, 7). Missing required elements are caught even when the application field is blank. |
| **Marcus:** standalone, nothing sensitive stored | No database, no COLA integration. Images are processed in memory and discarded. Logs record file name, verdict, and timing only. |

## How it works

1. **Preprocess** (`verifier/ocr.py`): fix EXIF rotation, resize only images
   that are very small or very large (resizing clean images made OCR worse in
   testing), equalise lighting, and straighten the image by finding the angle
   at which text rows line up most sharply (a projection-profile search on a
   small copy, ~100 ms).
2. **OCR** with Tesseract 5 (LSTM engine, sparse-text mode, since labels are
   scattered blocks rather than paragraphs). If very little text is found,
   retry at 90°, 180°, and 270°.
3. **Compare** (`verifier/matching.py`). Each check returns Pass, Review, or
   Fail with a plain-English message:
   - *Brand, class/type, bottler, country:* exact match → Pass; same words
     ignoring case/punctuation → Pass (difference shown); ≥90% similar →
     Review (probable OCR error); 75–90% → Review; otherwise Fail. Multi-line
     values like "Kentucky Straight / Bourbon Whiskey" match across line breaks.
   - *Alcohol content:* compares the percentage numerically; if the label
     states proof, checks proof = 2 × ABV.
   - *Net contents:* converts mL, cL, L, and fl oz to millilitres, 1% tolerance.
   - *Government warning:* heading must be in capitals; text must match word
     for word. A difference of a character or two (≥97% similar) goes to
     Review, because that is usually OCR misreading, not a creative applicant.
     Anything more is Fail.
4. **Bold heading:** estimates the stroke thickness of the `GOVERNMENT
   WARNING:` words (2 × ink area ÷ ink perimeter) and compares it to the body
   text. Heavier by 18% or more → bold. Not heavier → Review. Can't measure →
   note asking the agent to check. This never fails a label on its own,
   because a pixel heuristic isn't reliable enough to reject an application.
5. **Product-type rules** (`verifier/rules.py`). Comparing against the
   application isn't enough: if an application field is blank, a label
   missing that element would slip through. So for each product type the
   label is also checked for what TTB requires, citing the regulation in the
   result:

   | Element | Distilled spirits (part 5) | Wine (part 4) | Beer / malt (part 7) |
   |---|---|---|---|
   | Alcohol content | Required, as % by volume (proof alone fails) | Required over 14%; at 7–14% "table wine"/"light wine" may replace it | Optional unless alcohol comes from added flavors; if stated, "ABV" isn't allowed |
   | Net contents | Required | Required | Required |
   | Name and address | Required ("Bottled by", "Imported by"...) | Required | Required |
   | Country of origin | Required if the label says imported | Same | Same |
   | Other | — | "Contains sulfites" (Review if absent: depends on SO₂ level); table wine over 14% fails | — |
   | Health warning | Always | Always | Always |

   Brand name and class/type have no fixed wording, so they can only be
   checked against an application value. Items that depend on facts not
   visible on the label (sulfite levels, flavor-derived alcohol) go to
   **Needs review** or are noted, never failed.
6. **Overall verdict:** any Fail → Does not match; else any Review → Needs
   review; else Matches.

## Tools

- **Python 3.12, Flask** — small, readable server; gunicorn in production.
- **Tesseract 5** via `pytesseract` — mature, free, runs offline, easy to get
  through a security review.
- **OpenCV, NumPy, Pillow** — image preprocessing and bold measurement.
- **difflib** (standard library) — fuzzy matching and word-level diffs, so no
  extra dependency.
- **Plain HTML/CSS/JavaScript** — no build step, no framework, no external
  requests.
- **Docker** — one container, deployable to Azure App Service or any
  container host.
- **unittest** — standard library, so tests run with no extra installs.

## Why not a vision-language model (e.g. GPT-4o, Claude)?

A multimodal LLM would read hard photos better and could judge "same thing?"
more naturally. I chose local OCR for this prototype because the interviews
pointed to three hard constraints it satisfies and a cloud model may not:
the firewall that broke the last pilot, the 5-second limit (LLM vision calls
often take 3–10 s), and a federal environment where sending label images to a
third party needs approval. The matching layer takes plain text, so an
Azure-hosted model (Azure OpenAI is available in Azure Government) could be
added later as a second reader for low-confidence labels without changing
the rules.

## Assumptions

- The application data comes from the agent (typed in) or a CSV export,
  since COLA integration is out of scope.
- English-language labels; the warning text is the 27 CFR 16.21 wording.
- The agent selects the product type (or the CSV supplies it). If it's not
  given, only the rules common to all products run.
- Wines under 7% ABV aren't under TTB's part 4 labeling rules; the wine rules
  assume a wine within TTB's scope.
- One image per label (front and back panels combined, or the panel that
  carries the fields being checked).
- Blank application fields are skipped; the warning is always checked because
  it is mandatory on every alcohol beverage.
- "Brand name" matches if it appears anywhere on the label; the tool doesn't
  judge placement or prominence.
- Test labels are generated (`samples/generate_samples.py`) so every scenario
  has a known correct answer.

## Limitations and next steps

- **Bold detection is a heuristic.** It works on clear images; on poor photos
  it usually reports "couldn't measure" and asks for a human check.
- **Font size, placement, and contrast rules** (e.g. minimum type sizes for
  the warning) aren't checked.
- **Product-type rules cover the core mandatory elements**, not every
  conditional one (e.g. wine appellation and vintage rules, spirits age and
  neutral-spirits statements, color additive disclosures, standards of
  fill, "same field of vision"). Each is a small function in `rules.py`.
- **State-law requirements** (some states require or prohibit alcohol content
  on beer) aren't modelled.
- **Very poor images** (heavy blur, curved bottles photographed in the round)
  will produce Review/Fail results. The tool says when text was hard to read,
  so the agent knows to check by eye or request a better image.
- **Batch runs in the browser.** Closing the tab stops the batch. A production
  version would use a server-side job queue so large batches survive a
  refresh.
- **No authentication.** Fine for a prototype with no stored data; a
  production deployment would sit behind the agency's SSO.
