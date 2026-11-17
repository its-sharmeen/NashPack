# Label Register — SIH 2026, PS 26034

**Automated compliance-checking system for packaged commodities under the
Legal Metrology (Packaged Commodities) Rules, 2011**, built for Smart India
Hackathon Problem Statement 26034 (Department of Consumer Affairs).

Upload one or multiple package views (front/back/side) in a single inspection. The system reads it, checks it against
the mandatory declarations required under **Rule 6** (and the broader rule
set — applicability, placement, lettering size, exemptions, wholesale/export
packages, etc.), scores it, and produces a downloadable compliance
certificate — plus a searchable enforcement register of every scan.

## What it checks

| # | Declaration | Rule | Mandatory? |
|---|---|---|---|
| 1 | Name & address of manufacturer / packer / importer | 6(1)(a) | Yes |
| 2 | Country of origin | 6(1)(b) | Only if imported |
| 3 | Common / generic name of the commodity | 6(1)(c) | Yes |
| 4 | Net quantity (standard unit: g / kg / ml / l / number) | 6(1)(d) | Yes |
| 5 | Month & year of manufacture / pre-packing / import | 6(1)(e) | Yes |
| 6 | Best before / use-by, where applicable | 6(1)(f) | Conditional |
| 7 | Maximum Retail Price, inclusive of all taxes | 6(1)(g) | Yes |
| 8 | Dimensions, where relevant to the commodity | 6(1)(h) | Conditional |
| 9 | Consumer / customer care details | 6(1)(i) | Yes |

Beyond the nine declarations above, the rule engine (`core/compliance_engine.py`)
also evaluates ~15 further provisions — applicability (Rule 3/4), lettering
size (Rule 7), placement (Rule 8), unit standards (Rules 11–13), special
commodities such as textiles/dimensions (Rules 14–17), unit sale price
(6(11)), wholesale/export packages (Rules 24/25), exemptions (Rule 26), and
more — each returned as `PASS` / `FAIL` / `REVIEW_REQUIRED` / `N/A` with a
plain-language reason, so every decision is traceable to a specific rule.

**Design principle:** the engine never claims something a photograph can't
prove. Physical facts (actual net quantity, statutory lettering height in
millimetres, registration records) are always routed to `REVIEW_REQUIRED`
with a note that they need in-person verification by an officer — this is
called out explicitly in the report rather than silently assumed compliant.

## Architecture

```
Browser (upload label photo)
        │
        ▼
Flask app (app.py)
        │
        ├──► core/vlm_extractor.py       PRIMARY: sends the image to a
        │                                Gemini vision-language model,
        │                                which reads the label directly
        │                                (no OCR) and returns structured
        │                                JSON — declared values plus a
        │                                per-field visibility/readability
        │                                assessment.
        │
        ├──► core/ocr_fallback_extractor.py   FALLBACK: if the VLM call
        │      + core/ocr_engine.py           fails (no API key, no
        │                                     network, quota/timeout —
        │                                     all realistic at a demo
        │                                     venue), the system falls
        │                                     back to fully local OCR
        │                                     (OpenCV preprocessing +
        │                                     Tesseract) and regex
        │                                     extraction, filling the
        │                                     same schema at lower
        │                                     confidence. The UI always
        │                                     discloses which path was
        │                                     used.
        │
        ├──► core/compliance_engine.py    Rule engine: maps extracted
        │                                fields (from either path) onto
        │                                each LM(PC) Rules, 2011
        │                                provision, decides
        │                                COMPLIANT / COMPLIANT_WITH_
        │                                WARNINGS / NON_COMPLIANT /
        │                                REQUIRES_RESCAN, and scores it.
        │
        ├──► core/report_generator.py     Renders a downloadable PDF
        │                                compliance certificate
        │                                (ReportLab). CSV export
        │                                (app.py) covers the "editable
        │                                format" requirement.
        │
        ├──► core/auth.py                 Session-based officer/admin
        │                                login gating scanning, the
        │                                register, and report downloads.
        │
        └──► core/db.py                   SQLite-backed scan history —
                                          powers the register/dashboard,
                                          search/filter, and stats.
```

## Running it

Requires Python 3.10+ and, for the offline OCR fallback path, the
Tesseract OCR binary.

```bash
# system dependency (Ubuntu/Debian) — needed only for the OCR fallback
sudo apt-get install tesseract-ocr

# python dependencies
pip install -r requirements.txt

# configuration
cp .env.example .env
# then edit .env: add your GEMINI_API_KEY (https://aistudio.google.com/apikey)
# and set real officer credentials in LM_AUTH_USERS

python app.py
```

Then open `http://localhost:5000`. Sign in at `/login` with a
`LM_AUTH_USERS` account to scan labels or view the register.

**No Gemini API key / no internet at the venue?** The app still works —
every scan automatically falls back to the local OCR path and says so on
the result page.

## Pages

- `/` — landing page + headline stats + recent scans
- `/login` — officer/admin sign-in (session-based)
- `/scan` — upload a label photo, run a check *(requires login)*
- `/result/<id>` — declaration-by-declaration certificate for one scan,
  with PDF and CSV downloads *(requires login)*
- `/dashboard` — full enforcement register, searchable by product name /
  scan ID / any detected text, filterable by status *(requires login)*
- `/api/scans` — JSON feed of scan history, same search/filter params
  *(requires login)*
- `/report/<id>.pdf`, `/report/<id>.csv` — downloadable compliance report
  in a fixed (PDF) and an editable (CSV) format

## Security notes

- Secrets (`GEMINI_API_KEY`, `LM_AUTH_USERS`, `FLASK_SECRET_KEY`) live only
  in `.env`, which is git-ignored. `.env.example` holds placeholders only —
  **never commit real credentials to `.env.example` or anywhere in the repo.**
- Authentication is a demo-grade, session-cookie login backed by an env
  var. It is enough to gate the enforcement UI for a hackathon/pilot but is
  explicitly **not** a production identity system — see "Next steps" below.

## Known limitations (be upfront about these when presenting)

- **This is a heuristic prototype, not a certified legal tool.** Every
  result page and PDF says so explicitly.
- **Font-size/readability is indicative only.** The VLM/OCR paths flag an
  *obvious* lettering-size problem but cannot measure millimetres from an
  ordinary photograph without a size reference (e.g. an QR reference or
  known-size object) in frame.
- **The "common/generic name" check is a heuristic** in the OCR fallback
  path (first substantial text line); the Gemini VLM path is considerably
  more reliable here because it reasons over the whole label, not just
  line order.
- **Actual net-quantity accuracy, statutory lettering dimensions, and
  registration status can never be established from a photograph alone**
  — the rule engine deliberately marks these `REVIEW_REQUIRED` /
  `PHYSICAL_TEST_REQUIRED` rather than guessing, because that's the
  legally honest answer.
- OCR fallback accuracy depends on photo quality — curved bottles, glare,
  and low light reduce recall more than they do for the VLM path.

## Suggested next steps for the full submission

1. Replace the env-var login with a real credential store (hashed +
   salted passwords, or SSO/LDAP against the department directory) and add
   an audit trail of every login and report download.
2. Add a mobile-first capture flow (camera guide overlay, since field
   inspectors will be shooting labels handheld, not uploading files).
3. Persist to Postgres instead of SQLite for multi-officer concurrent use.
4. Add bulk/batch mode: scan an e-commerce listing's full image gallery
   in one pass.
5. Give the OCR fallback path a size-reference option (place a known-size
   card in frame) so the font-size check becomes a real millimetre
   measurement rather than a heuristic, for both extraction paths.

## SIH26034 Rule Engine v2 — Declaration & Presentation Layers

The compliance engine now separates extraction from deterministic validation:

- `core/rule_registry.py` — complete rule register used for serial reporting.
- `core/applicability_engine.py` — scope/context classification and conservative applicability decisions.
- `core/declaration_engine.py` — deterministic Rule 6 declaration validation.
- `core/presentation_engine.py` — Rules 7–13 presentation/readability/quantity screening.

A detected string is no longer automatically treated as legally compliant. The system distinguishes `PASS`, `FAIL`, `REVIEW_REQUIRED`, and `N/A`. Physical quantity accuracy, registration records, dealer conduct and other image-unprovable requirements remain `REVIEW_REQUIRED`.

The legal registry is based on the Department of Consumer Affairs consolidated 2011 rules and operative amendments verified for this build. Draft amendments are not treated as operative law.


## v4 Compliance Fixes

- Domestic packages are no longer treated as imported merely because a country-of-origin field is visible.
- Dates such as `26.05.16` are accepted as containing a valid month/year component for Rule 6(1)(d); the system does not pretend to verify physical print format from pixels.
- Compact quantity strings such as `200g` are correctly recognized by Rules 11 and 13.
- Rule 26 no longer reports `FAIL` merely because no exemption was detected; absence of an exemption is `NOT_APPLICABLE`.
- Rule 10 now requires a name/address pair before reporting a package-level PASS.
- Top-level Rule 6 includes Rule 6(11) in its derived status.
- Console messaging now accurately says OCR is a fallback, not disabled.
- Added regression tests under `tests/`.

## SIH26034 font-size measurement strategy

The primary package-perception path remains Gemini VLM. OCR is only the fallback.
The VLM can return normalized evidence bounding boxes (`evidence_regions`) for
visible declarations. The annotation layer renders these regions on the original
image.

Physical lettering height is deliberately not inferred from pixels alone. When a
known-size QR physical reference is visible, the calibration layer estimates
mm-per-pixel and the font-measurement layer converts the VLM-localized text region
to an estimated physical height. If no QR reference is detected, the system reports
`REVIEW_REQUIRED` rather than inventing a millimetre measurement.

This marker is a calibration reference, not a manual ruler reading. The system
detects the marker automatically. The optional AR/mobile capture layer can later
use the same marker while guiding the camera and package-plane capture.


## Competition-ready upgrades in this build

- Multi-view inspection: front/back/side images are submitted together and their semantic observations are merged before compliance scoring.
- Gemini VLM remains the primary perception engine. Local OCR remains only a fallback when Gemini is unavailable and the UI explicitly discloses that path.
- Calibrated lettering measurement: a known 50 mm QR reference can establish mm-per-pixel scale. The system estimates lettering height in mm from Gemini-localized regions and, when PDP geometry is available, compares it with the Rule 7 minimum table.
- Camera capture: the scan page can open the device camera, capture several views, and submit them with uploaded images.
- Evidence annotation: VLM evidence boxes and the PDP region are drawn on every inspected view; QR calibration reference is highlighted.
- Applicability-first reporting: package classification and Rule 3/Rule 26 signals are surfaced before the full rule register.
- Measurement honesty: no QR reference means no millimetre claim; curved/unknown geometry remains review-required.

For a defensible font-size demo, print the supplied 50 mm QR reference, place it beside the package on the same planar surface, and capture the whole panel without perspective-heavy distortion.


## v7 classification and annotation safeguards
- Gemini remains the primary visual perception engine.
- Product category is explicitly classified from visual/package evidence (FOOD, ELECTRONIC, GARMENT_TEXTILE, etc.) with confidence and evidence.
- Food classification also has a conservative backward-compatible fallback using FSSAI/ingredients/food terms when older VLM JSON lacks the category field.
- Wholesale/export/industrial context remains evidence-based; a front image alone cannot reliably prove wholesale status.
- Annotation regions are semantically deduplicated and the tighter overlapping region is preferred, preventing product-name/common-name boxes from stacking.
