"""
Offline fallback extractor.

The primary extraction path is the Gemini VLM (core/vlm_extractor.py).
That needs an internet connection and a valid GEMINI_API_KEY. Hackathon
demo venues are notorious for flaky wifi, and a judge asking "what if
the API is down?" is one of the most common questions this kind of
project gets — so this module answers it: if the VLM call fails for
*any* reason (no key, no network, quota, timeout), app.py falls back
to a local OCR + regex extractor that fills in the same JSON schema
`compliance_engine.run_compliance_check` expects.

It is deliberately conservative: fields it can't confidently find stay
None/UNKNOWN rather than guessing, so the compliance engine correctly
routes them to FAIL/REVIEW_REQUIRED instead of a false PASS.
"""

import re

from core.ocr_engine import run_ocr


_MONTHS = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
    "|january|february|march|april|june|july|august|september|october|november|december"
)


def _find(pattern, text, flags=re.IGNORECASE):
    m = re.search(pattern, text, flags)
    if not m:
        return None
    return m.group(1).strip(" .:-\t") or None


def extract_with_ocr(image_path):
    ocr = run_ocr(image_path)
    text = ocr["text"] or ""
    words = ocr.get("words", [])
    img_h = ocr.get("image_size", {}).get("height") or 0

    # --- net quantity: e.g. "Net Wt. 200g", "500 ml", "1 kg" ---
    net_quantity = _find(
        r"(?:net\s*(?:wt\.?|weight|qty\.?|quantity)?\s*[:\-]?\s*)?(\d+(?:\.\d+)?\s?(?:kg|g|mg|ml|l|litre|liter|ltr)\b)",
        text,
    )

    # --- MRP ---
    mrp = _find(r"(?:mrp|m\.r\.p\.?|max(?:imum)?\s*retail\s*price)[:.\-]?\s*(?:rs\.?|inr|₹)?\s*([\d,]+(?:\.\d{1,2})?)", text)
    mrp_inclusive = bool(re.search(r"incl(?:usive|\.)?\s*of\s*(?:all\s*)?tax", text, re.IGNORECASE))

    # --- manufacturing date: "MFD 26.05.16", "Mfg Date: 05/2026", month-year ---
    manufacturing_date = _find(
        r"(?:mfd|mfg\.?\s*(?:date)?|manufactured\s*(?:on|date)?|packed\s*on)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}[./-]\d{2,4}|(?:" + _MONTHS + r")\.?\s*\d{4})",
        text,
    )

    expiry = _find(
        r"(?:exp\.?|expiry|best\s*before|use\s*by)\s*[:\-]?\s*(\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{1,2}[./-]\d{2,4}|(?:" + _MONTHS + r")\.?\s*\d{4})",
        text,
    )

    # --- manufacturer / packer block ---
    manufacturer_line = _find(
        r"(?:manufactured\s*(?:&|and)?\s*(?:marketed)?\s*by|packed\s*by|marketed\s*by|mfd\.?\s*by)\s*[:\-]?\s*([^\n]{5,120})",
        text,
    )

    # --- consumer care ---
    consumer_care = _find(
        r"(?:consumer\s*care|customer\s*care|for\s*(?:complaints|feedback)|toll[\s-]?free|helpline)\s*[:\-]?\s*([^\n]{5,120})",
        text,
    )
    if not consumer_care:
        consumer_care = _find(r"((?:\+?91[\s-]?)?\d{10}|\d{4}[\s-]\d{3}[\s-]\d{4})", text)

    country_of_origin = _find(r"country\s*of\s*origin\s*[:\-]?\s*([A-Za-z ]{3,40})", text)
    is_imported = bool(country_of_origin) or bool(re.search(r"\bimported\b", text, re.IGNORECASE))

    # --- common/generic name: heuristic = first substantial line, always
    # flagged for manual verification by the compliance engine ---
    common_name = None
    for line in text.splitlines():
        line = line.strip()
        if len(line) >= 4 and re.search(r"[A-Za-z]{3,}", line):
            common_name = line
            break

    # --- font-size heuristic: flag if most detected word heights are
    # very small relative to image height (indicative only) ---
    font_issue = False
    if words and img_h:
        heights = [w["height_px"] for w in words if w.get("height_px")]
        if heights:
            median_h = sorted(heights)[len(heights) // 2]
            if median_h / img_h < 0.012:  # smaller than ~1.2% of image height
                font_issue = True

    def _visibility(value):
        return "CLEAR" if value else "NOT_VISIBLE"

    result = {
        "brand_name": None,
        "product_name": common_name,
        "common_name": common_name,
        "manufacturer_name": manufacturer_line,
        "manufacturer_address": manufacturer_line,
        "importer_name": None,
        "importer_address": None,
        "net_quantity": net_quantity,
        "mrp": mrp,
        "mrp_inclusive_of_taxes": mrp_inclusive,
        "batch_number": _find(r"(?:batch\s*no\.?|b\.?\s*no\.?)\s*[:\-]?\s*([A-Za-z0-9\-/]{3,20})", text),
        "manufacturing_date": manufacturing_date,
        "expiry_or_best_before": expiry,
        "fssai_numbers": re.findall(r"\b(1\d{13})\b", text),
        "consumer_care": consumer_care,
        "country_of_origin": country_of_origin,
        "unit_sale_price": _find(r"(₹\s?\d+(?:\.\d+)?\s?/\s?(?:kg|g|ml|l))", text),
        "dimensions": None,
        "dimensions_relevant": None,
        "is_imported": is_imported,
        "industrial_or_institutional": False,
        "agricultural_farm_produce_or_cement_fertilizer_over_50kg": False,
        "exempt_small_package": False,
        "restaurant_or_hotel_fast_food": False,
        "medical_device_or_drug": False,
        "wholesale_package": False,
        "export_package": bool(re.search(r"\bfor\s*export\b", text, re.IGNORECASE)),
        "combination_or_multi_piece_package": False,
        "visual_analysis": {
            "image_quality": "CLEAR" if ocr.get("avg_confidence", 0) >= 40 else "UNKNOWN",
            "overall_readability": "CLEAR" if ocr.get("avg_confidence", 0) >= 40 else "UNKNOWN",
            "manufacturer_visibility": _visibility(manufacturer_line),
            "product_name_visibility": _visibility(common_name),
            "common_name_visibility": _visibility(common_name),
            "quantity_visibility": _visibility(net_quantity),
            "mrp_visibility": _visibility(mrp),
            "date_visibility": _visibility(manufacturing_date),
            "consumer_care_visibility": _visibility(consumer_care),
            "mandatory_text_readability": "CLEAR" if ocr.get("avg_confidence", 0) >= 40 else "UNKNOWN",
            "declaration_placement": "UNKNOWN",
            "blur_detected": ocr.get("avg_confidence", 0) < 25,
            "occlusion_detected": False,
            "possible_font_size_issue": font_issue,
            "visual_warnings": (
                ["OCR fallback mode: extraction quality is lower than the VLM path — verify manually."]
            ),
        },
        "evidence": [w["word"] for w in words[:25]],
        "_extraction_source": "OCR_FALLBACK",
        "_ocr_confidence": ocr.get("avg_confidence", 0),
    }

    return result
