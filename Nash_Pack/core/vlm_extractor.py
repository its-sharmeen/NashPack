import os
import json
import re
import mimetypes

from google import genai
from google.genai import types


def _model_name():
    # Read at call time (not import time) so tests / .env reloads work,
    # and fall back to a real, currently-available Gemini model rather
    # than a hardcoded name that may not exist.
    return os.getenv("GEMINI_MODEL") or os.getenv("GEMINI_VLM_MODEL") or "gemini-2.5-flash"


def _clean_json(text):

    if not text:
        return {}

    text = text.strip()

    # Remove markdown fences
    text = re.sub(
        r"^```json\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"^```\s*",
        "",
        text,
    )

    text = re.sub(
        r"\s*```$",
        "",
        text,
    )

    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to extract first JSON object
    match = re.search(
        r"\{.*\}",
        text,
        flags=re.DOTALL,
    )

    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    return {}


def _client():

    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY environment variable is not set."
        )

    return genai.Client(api_key=api_key)


def extract_with_vlm(image_path):

    client = _client()

    prompt = r"""
You are the primary visual inspection engine for Smart India Hackathon
problem statement SIH26034.

The task is:

CHECK A PRE-PACKAGED COMMODITY LABEL AGAINST THE
LEGAL METROLOGY (PACKAGED COMMODITIES) RULES, 2011
AND APPLICABLE AMENDMENTS.

IMPORTANT:

1. DO NOT USE OCR.
2. DO NOT pretend that OCR was used.
3. You are a Gemini Vision Language Model and must inspect the image directly.
4. Read text visually from the image.
5. Do not invent information.
6. If something cannot be confidently seen, return null or UNKNOWN.
7. Evidence must contain text that is actually visible in the image.
8. Keep the original wording where possible.
9. Do not hallucinate legal compliance.
10. Separate:
      - what is visibly detected
      - what is legally applicable
      - what requires contextual/physical verification.

========================================================
OUTPUT FORMAT
========================================================

Return ONLY valid JSON.

Use exactly this top-level structure:

{
  "brand_name": null,
  "product_name": null,
  "common_name": null,

  "manufacturer_name": null,
  "manufacturer_address": null,

  "importer_name": null,
  "importer_address": null,

  "net_quantity": null,
  "mrp": null,
  "mrp_inclusive_of_taxes": null,

  "batch_number": null,
  "manufacturing_date": null,
  "expiry_or_best_before": null,

  "fssai_numbers": [],
  "consumer_care": null,
  "country_of_origin": null,

  "unit_sale_price": null,
  "dimensions": null,

  "is_imported": false,

  "industrial_or_institutional": false,
  "agricultural_farm_produce_or_cement_fertilizer_over_50kg": false,
  "exempt_small_package": false,
  "restaurant_or_hotel_fast_food": false,
  "medical_device_or_drug": false,

  "wholesale_package": false,
  "export_package": false,
  "combination_or_multi_piece_package": false,
  "sold_loose_or_open": false,
  "advertising_context": false,

  "product_category": "UNKNOWN",
  "product_category_confidence": 0.0,
  "category_evidence": [],

  "dimensions_relevant": null,

  "visual_analysis": {
    "image_quality": "CLEAR",
    "overall_readability": "CLEAR",

    "manufacturer_visibility": "CLEAR",
    "product_name_visibility": "CLEAR",
    "common_name_visibility": "CLEAR",
    "quantity_visibility": "CLEAR",
    "mrp_visibility": "CLEAR",
    "date_visibility": "CLEAR",
    "consumer_care_visibility": "CLEAR",

    "mandatory_text_readability": "CLEAR",

    "declaration_placement": "UNKNOWN",

    "blur_detected": false,
    "occlusion_detected": false,
    "possible_font_size_issue": false,

    "visual_warnings": []
  },

  "evidence": [],

  "evidence_regions": [],
  "pdp_evidence": {
    "bbox": null,
    "confidence": 0.0
  }
}

========================================================
VISUAL STATUS RULES
========================================================

For every visual field use ONLY:

CLEAR
NOT_VISIBLE
OBSCURED
BLURRED
UNKNOWN

Do not use random alternatives.

Meaning:

CLEAR:
The relevant declaration is visibly present and readable.

NOT_VISIBLE:
You inspected the relevant package area but could not find the declaration.

OBSCURED:
The declaration appears to exist but is blocked/cut off/covered.

BLURRED:
The declaration appears present but cannot be read reliably because of blur.

UNKNOWN:
The image does not allow a reliable determination.

VERY IMPORTANT:

Do NOT return NOT_VISIBLE merely because the exact legal placement
cannot be determined.

Example:

If you can clearly see:

"CLASSIC salted PEANUTS"

then:

"product_name_visibility": "CLEAR"

even if exact Rule 8 placement cannot be established.

========================================================
DECLARATION PLACEMENT
========================================================

"declaration_placement" is different from visibility.

Use:

CLEAR
when the principal display panel / placement can reasonably be assessed.

UNKNOWN
when the photograph does not provide enough geometric/contextual evidence.

Do NOT mark an otherwise visible declaration as NOT_VISIBLE merely
because placement is UNKNOWN.

========================================================
IMAGE QUALITY
========================================================

Use:

CLEAR
if the package can be inspected reasonably well.

UNKNOWN
only if image quality cannot confidently be assessed.

Do not return UNKNOWN by default.

========================================================
COMMON / GENERIC PRODUCT NAME
========================================================

This is very important.

The common/generic name may be contained in the product title.

Examples:

"CLASSIC salted PEANUTS"
"SUGAR"
"TOOR DAL"
"BATH SOAP"

If such a name is clearly visible, set:

common_name = the visible name

and:

common_name_visibility = CLEAR
product_name_visibility = CLEAR

Do NOT set NOT_VISIBLE if the product name is actually visible.

========================================================
MRP
========================================================

Look for:

MRP
Maximum Retail Price
Rs.
₹

Also determine whether the package explicitly says:

"Incl. of all taxes"
"Inclusive of all taxes"

If explicitly visible:

mrp_inclusive_of_taxes = true

If MRP is visible but tax inclusion is not explicitly visible:

mrp_inclusive_of_taxes = false

Do not assume tax inclusion without visual evidence.

========================================================
MANUFACTURER
========================================================

Look for:

Manufactured by
Manufactured & Marketed by
Packed by
Manufactured/packed by
Manufacturer name/address

Extract both name and address when visible.

========================================================
COUNTRY OF ORIGIN
========================================================

Only set is_imported=true when the package clearly indicates
that it is imported or clearly identifies an importer.

If an Indian manufacturer is shown and no import indication exists:

is_imported=false

If imported:

extract country_of_origin if visibly available.

========================================================
UNIT SALE PRICE
========================================================

Look carefully for:

per gram
per kg
per ml
per litre
per unit
per number

Examples:

"₹0.22 / g"
"₹220 / kg"

If not visible:

unit_sale_price = null

Do NOT automatically call this non-compliant because applicability
can depend on package category and the relevant provisions.

========================================================
DIMENSIONS
========================================================

Only mark dimensions_relevant=true when the commodity type appears
to require dimensions under special provisions.

Examples can include:

bedsheets
fabrics
sarees
dhoti
towels
napkins
pillow covers
table cloths
foil
tissues
toilet paper
certain containers

For ordinary food packets such as peanuts:

dimensions_relevant=false

Do NOT invent dimensions.

========================================================
PRODUCT CATEGORY CLASSIFICATION
========================================================

Classify the physical commodity itself, not merely words in its name.
Return exactly one primary product_category:

FOOD
ELECTRONIC
GARMENT_TEXTILE
COSMETIC_PERSONAL_CARE
HOUSEHOLD_CLEANING
TOILETRY
STATIONERY
TOY
FOOTWEAR
MEDICAL_DEVICE
DRUG
AGRICULTURAL
CEMENT_FERTILIZER
OTHER
UNKNOWN

Also return product_category_confidence from 0 to 1 and 1-3 short
category_evidence strings containing visible clues from the package.

Use multiple visual clues together. For FOOD, strong clues include an edible
commodity, ingredients, nutrition information, FSSAI licence/logo, food-use
language, milk/food contents, or a clearly food product name. A food packet
should not be classified as false merely because the exact English word
"food" is absent.

For ELECTRONIC, look for an electronic device/accessory and technical model,
power, voltage, battery, input/output or electrical markings.

For GARMENT_TEXTILE, look for clothing/fabric/textile articles and textile
labelling.

For MEDICAL_DEVICE/DRUG, rely on visible medical/drug identity and packaging,
not generic words such as "care".

For AGRICULTURAL/CEMENT_FERTILIZER, look for the actual commodity and relevant
package markings; do not infer the >50 kg Rule 3 case without quantity/context.

========================================================
CONTEXT FLAGS
========================================================

These flags must be conservative.

industrial_or_institutional:
true only if package explicitly indicates industrial/institutional use.

agricultural_farm_produce_or_cement_fertilizer_over_50kg:
true only when clearly applicable.

exempt_small_package:
true only when the package is clearly within an exemption category.

restaurant_or_hotel_fast_food:
true only when clearly evident.

medical_device_or_drug:
true only when clearly evident.

wholesale_package:
true only when the package clearly appears to be a wholesale package.

export_package:
true only when clearly marked as export.

combination_or_multi_piece_package:
true when package clearly contains a combination/group/multi-piece product.

========================================================
RULE 7
========================================================

possible_font_size_issue:

true only if there is an obvious visual problem with lettering size.

Otherwise:

false

Do NOT claim exact statutory font-size compliance from a photograph.

========================================================
RULE 22
========================================================

Do not claim that a photograph proves actual quantity accuracy.

The package may say:

"200g"

but a photograph cannot establish whether the physical quantity
actually equals 200g.


========================================================
PRINCIPAL DISPLAY PANEL (PDP) GEOMETRY
========================================================

If the principal display panel can be visually identified, return a tight
normalized bounding box in principal_display_panel_bbox using [x1,y1,x2,y2]
on the ORIGINAL IMAGE in the same 0..1000 coordinate system as evidence_regions.
Do not invent it. If the package is curved or the PDP cannot be reliably localized,
return null and package_surface_shape="CURVED" or "UNKNOWN".
If it is reasonably planar, use package_surface_shape="PLANAR".
This geometry is used only for calibrated measurement; it is not itself a legal
conclusion.

========================================================
EVIDENCE REGIONS / BOUNDING BOXES
========================================================

For every important declaration or label text that you can localize, add an
object to evidence_regions. Bounding boxes MUST use Gemini's standard normalized 0..1000 coordinate system
relative to the ORIGINAL IMAGE, in the form:
[ymin, xmin, ymax, xmax]
where (0,0) is the top-left and (1000,1000) is the bottom-right.
IMPORTANT: the first and third values are Y coordinates; the second and fourth
values are X coordinates. Do not return [xmin,ymin,xmax,ymax].

Use this structure:
{
  "field": "mrp",
  "text": "MRP ₹250",
  "bbox": [650, 410, 705, 650],
  "confidence": 0.96
}

Allowed field examples:
brand_name, product_name, common_name, manufacturer_name,
manufacturer_address, importer_name, importer_address, net_quantity, mrp,
manufacturing_date, expiry_or_best_before, consumer_care, country_of_origin,
batch_number, dimensions, fssai_number

Rules:
- Only create a region when the text is actually visible.
- Do not invent coordinates.
- Keep the box TIGHT around the visible glyphs/characters, not around the surrounding
  package area, paragraph, panel, logo, or semantic section.
- The four coordinates should closely hug the outermost visible letters/numerals.
- Do not include large empty margins: normally keep padding to about 1-3% of image
  width/height around the text.
- For a single line, bbox height should be close to the visible line height, not the
  height of the whole label or panel.
- Use one region per distinct declaration where practical.
- Do NOT reuse one large bbox for product_name and common_name unless they are the
  same exact visible text at the same location.
- If the text cannot be localized tightly with confidence, omit the region rather
  than returning a large approximate box.
- confidence must be a number from 0 to 1.
- The bbox is for localization/annotation, not a physical millimetre measurement.

========================================================
EVIDENCE
========================================================

The evidence array must contain short pieces of text actually visible
on the package.

For example:

[
  "Haldiram's",
  "CLASSIC salted PEANUTS",
  "Net Wt. : 200g",
  "MRP : Rs 44.00",
  "(Incl. of all taxes)",
  "MFD : 26.05.16",
  "B. No. : HC 511C"
]

Do not add legal conclusions to evidence.

========================================================
FINAL INSTRUCTION
========================================================

Inspect the image carefully.

Use the actual visual content.

Do not hallucinate.

Return ONLY JSON.
"""

    with open(image_path, "rb") as f:
        image_bytes = f.read()

    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"

    response = client.models.generate_content(
        model=_model_name(),
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            ),
            prompt,
        ],
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )

    result = _clean_json(
        response.text
        if response
        else ""
    )

    if not result:
        raise RuntimeError(
            "Gemini returned an empty or invalid JSON response."
        )

    # --------------------------------------------------------
    # SAFE DEFAULTS
    # --------------------------------------------------------

    result.setdefault("evidence", [])
    result.setdefault("evidence_regions", [])
    result.setdefault("principal_display_panel_bbox", None)
    result.setdefault("package_surface_shape", "UNKNOWN")
    result.setdefault("product_category", "UNKNOWN")
    result.setdefault("product_category_confidence", 0.0)
    result.setdefault("category_evidence", [])
    result.setdefault("fssai_numbers", [])

    result.setdefault("is_imported", False)
    result.setdefault(
        "industrial_or_institutional",
        False,
    )
    result.setdefault(
        "agricultural_farm_produce_or_cement_fertilizer_over_50kg",
        False,
    )
    result.setdefault(
        "exempt_small_package",
        False,
    )
    result.setdefault(
        "restaurant_or_hotel_fast_food",
        False,
    )
    result.setdefault(
        "medical_device_or_drug",
        False,
    )
    result.setdefault(
        "wholesale_package",
        False,
    )
    result.setdefault(
        "export_package",
        False,
    )
    result.setdefault(
        "combination_or_multi_piece_package",
        False,
    )

    visual = result.setdefault(
        "visual_analysis",
        {},
    )

    visual.setdefault(
        "image_quality",
        "UNKNOWN",
    )

    visual.setdefault(
        "overall_readability",
        "UNKNOWN",
    )

    visual.setdefault(
        "manufacturer_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "product_name_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "common_name_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "quantity_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "mrp_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "date_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "consumer_care_visibility",
        "UNKNOWN",
    )

    visual.setdefault(
        "mandatory_text_readability",
        "UNKNOWN",
    )

    visual.setdefault(
        "declaration_placement",
        "UNKNOWN",
    )

    visual.setdefault(
        "blur_detected",
        False,
    )

    visual.setdefault(
        "occlusion_detected",
        False,
    )

    visual.setdefault(
        "possible_font_size_issue",
        False,
    )

    visual.setdefault(
        "visual_warnings",
        [],
    )

    # --------------------------------------------------------
    # IMPORTANT CONSISTENCY FIX
    # --------------------------------------------------------
    # If Gemini extracted a product name but visual model accidentally
    # says NOT_VISIBLE, correct it because the same VLM has already
    # established that the text was visually detected.

    if result.get("product_name"):
        if visual.get("product_name_visibility") == "NOT_VISIBLE":
            visual["product_name_visibility"] = "CLEAR"

    if result.get("common_name"):
        if visual.get("common_name_visibility") == "NOT_VISIBLE":
            visual["common_name_visibility"] = "CLEAR"

    if result.get("net_quantity"):
        if visual.get("quantity_visibility") == "NOT_VISIBLE":
            visual["quantity_visibility"] = "CLEAR"

    if result.get("mrp"):
        if visual.get("mrp_visibility") == "NOT_VISIBLE":
            visual["mrp_visibility"] = "CLEAR"

    if result.get("manufacturing_date"):
        if visual.get("date_visibility") == "NOT_VISIBLE":
            visual["date_visibility"] = "CLEAR"

    if result.get("manufacturer_name"):
        if visual.get("manufacturer_visibility") == "NOT_VISIBLE":
            visual["manufacturer_visibility"] = "CLEAR"

    if result.get("consumer_care"):
        if visual.get("consumer_care_visibility") == "NOT_VISIBLE":
            visual["consumer_care_visibility"] = "CLEAR"

    return result