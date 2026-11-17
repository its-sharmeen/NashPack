"""Deterministic declaration validation for SIH26034.

This module intentionally separates "text detected" from "declaration compliant".
It validates structure/format that can reasonably be inferred from extracted data;
legal/contextual and physical questions remain REVIEW_REQUIRED.
"""
import re
from decimal import Decimal, InvalidOperation


def _text(v):
    return str(v or "").strip()


def _has(v):
    return bool(_text(v))


def _valid_phone(v):
    if not _has(v):
        return False
    digits = re.sub(r"\D", "", _text(v))
    return 7 <= len(digits) <= 15


def _valid_email(v):
    if not _has(v):
        return False
    return bool(re.search(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", _text(v)))


def _quantity_parts(v):
    s = _text(v).lower().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*(kg|g|mg|l|litre|liter|ml|m|cm|mm|sq\.?\s*m|number|no\.?|nos?\.?|pcs?|pieces?)\b", s)
    if not m:
        return None
    try:
        return Decimal(m.group(1)), re.sub(r"\s+", "", m.group(2))
    except InvalidOperation:
        return None


def validate_declarations(vlm):
    """Return deterministic checks for Rule 6 declarations.

    PASS means the extracted declaration has enough structure for an image-based
    pre-screen. It does not certify physical/legal compliance.
    """
    # Country-of-origin text alone must NOT imply that the package is imported.
    # Imported status must come from an explicit classifier/VLM flag or importer data.
    imported = bool(vlm.get("is_imported")) or bool(vlm.get("importer_name")) or bool(vlm.get("importer_address"))
    manufacturer = _text(vlm.get("manufacturer_name"))
    manufacturer_address = _text(vlm.get("manufacturer_address"))
    importer = _text(vlm.get("importer_name"))
    importer_address = _text(vlm.get("importer_address"))
    product = _text(vlm.get("common_name") or vlm.get("product_name"))
    quantity = _text(vlm.get("net_quantity"))
    mfg = _text(vlm.get("manufacturing_date"))
    best_before = _text(vlm.get("expiry_or_best_before"))
    mrp = _text(vlm.get("mrp"))
    inclusive = bool(vlm.get("mrp_inclusive_of_taxes"))
    # Cross-view evidence can explicitly confirm the tax-inclusive MRP wording
    # even when Gemini's structured boolean is conservative. This remains VLM
    # evidence; no OCR is introduced here.
    evidence = vlm.get("evidence") or []
    if not inclusive and isinstance(evidence, list):
        evidence_text = " ".join(str(x) for x in evidence).lower()
        inclusive = bool(
            re.search(r"\b(?:incl\.?|inclusive)\s*(?:of)?\s*(?:all\s+)?tax(?:es)?\b", evidence_text)
            or "incl. of all taxes" in evidence_text
            or "incl of all taxes" in evidence_text
        )
    consumer = vlm.get("consumer_care")
    unit_sale = _text(vlm.get("unit_sale_price"))

    checks = []

    # 6(1)(a)
    if manufacturer and manufacturer_address:
        status = "PASS"
        reason = "Manufacturer/packer name and address were extracted as separate fields."
    elif imported and importer and importer_address:
        status = "PASS"
        reason = "Importer name and address were extracted for an imported package."
    else:
        status = "FAIL"
        reason = "Required manufacturer/packer details are incomplete; importer details are also required when applicable."
    checks.append(("Rule 6(1)(a)", status, manufacturer or importer or None, reason))

    # 6(1)(aa)
    if imported:
        status = "PASS" if _has(vlm.get("country_of_origin")) else "FAIL"
        reason = "Country of origin was detected for an imported package." if status == "PASS" else "Imported package detected but country of origin was not detected."
    else:
        status, reason = "N/A", "Package is not identified as imported."
    checks.append(("Rule 6(1)(aa)", status, vlm.get("country_of_origin"), reason))

    # 6(1)(b)
    status = "PASS" if product else "FAIL"
    reason = "Common/generic product name was detected." if status == "PASS" else "Common/generic product name was not detected."
    checks.append(("Rule 6(1)(b)", status, product or None, reason))

    # 6(1)(c)
    parts = _quantity_parts(quantity)
    if not quantity:
        status, reason = "FAIL", "Net quantity was not detected."
    elif parts:
        status, reason = "PASS", "Net quantity contains a recognizable quantity value and unit; actual quantity accuracy still requires physical verification."
    else:
        status, reason = "REVIEW_REQUIRED", "Net quantity was detected but its unit/format could not be normalized confidently."
    checks.append(("Rule 6(1)(c)", status, quantity or None, reason))

    # 6(1)(d)
    month_year = (
        bool(re.search(r"(?:0?[1-9]|1[0-2])\s*[-/.]\s*(?:20)?\d{2}\b", mfg))
        or bool(re.search(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+20\d{2}\b", mfg, re.I))
        or bool(re.search(r"\b(?:0?[1-3]?\d)[\s./-](?:0?[1-9]|1[0-2])[\s./-](?:20)?\d{2}\b", mfg))
    )
    if not mfg:
        status, reason = "FAIL", "Month/year of manufacture was not detected."
    elif month_year:
        status, reason = "PASS", "Manufacturing information matches a recognizable month/year pattern."
    else:
        status, reason = "REVIEW_REQUIRED", "Manufacturing information exists but its month/year format could not be normalized confidently."
    checks.append(("Rule 6(1)(d)", status, mfg or None, reason))

    # 6(1)(da) conditional
    if best_before:
        status, reason = "PASS", "Best-before/use-by information was detected."
    else:
        status, reason = "REVIEW_REQUIRED", "Best-before/use-by applicability depends on the commodity; absence cannot be conclusively judged from generic package data."
    checks.append(("Rule 6(1)(da)", status, best_before or None, reason))

    # 6(1)(e)
    if not mrp:
        status, reason = "FAIL", "MRP was not detected."
    elif inclusive:
        status, reason = "PASS", "MRP was detected and the VLM evidence identifies an inclusive-of-all-taxes declaration."
    else:
        status, reason = "REVIEW_REQUIRED", "MRP was detected, but the image extraction did not establish the required inclusive-of-all-taxes wording with sufficient confidence."
    checks.append(("Rule 6(1)(e)", status, mrp or None, reason))

    # 6(1)(f)
    phone = consumer.get("phone") if isinstance(consumer, dict) else None
    email = consumer.get("email") if isinstance(consumer, dict) else None
    raw_consumer = consumer if isinstance(consumer, str) else None
    if _valid_phone(phone) or _valid_email(email) or _has(raw_consumer):
        status, reason = "PASS", "Consumer-care contact information was detected; contact usability should still be checked against the printed package."
    else:
        status, reason = "FAIL", "Consumer-care contact details were not detected."
    checks.append(("Rule 6(1)(f)", status, consumer or None, reason))

    # 6(11) unit sale price: presence is not enough; compare expected unit when possible.
    if unit_sale:
        status, reason = "PASS", "Unit sale price was detected; numerical reconciliation is performed when MRP and net quantity can be normalized."
    else:
        status, reason = "REVIEW_REQUIRED", "Unit sale price was not detected; applicability and exemption conditions must be confirmed from package context."
    checks.append(("Rule 6(11)", status, unit_sale or None, reason))

    return {
        "checks": [
            {"rule": rid, "status": st, "detected_value": val, "reason": reason}
            for rid, st, val, reason in checks
        ],
        "imported": imported,
        "quantity_parts": [str(parts[0]), parts[1]] if parts else None,
    }
