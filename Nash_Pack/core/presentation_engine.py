"""Judge-facing presentation model for SIH26034 inspection results.

The compliance engine remains the source of legal decisions.  This module only
normalizes the result for the website/PDF/CSV so that:

* only applicable Legal Metrology declaration checks are shown together;
* each declaration has one final physical font height;
* Rule 7 measurement is shown as measured-vs-required;
* multiple QR-calibrated views remain drill-down evidence;
* global visual readability/placement is shown once, not repeated per row.
"""

from collections import Counter
from statistics import median

from core.font_measurement import FONT_CANONICAL


DECLARATION_RULES = {
    "Rule 6(1)(a)": ("Manufacturer / Packer / Importer", "manufacturer"),
    "Rule 6(1)(aa)": ("Country of Origin (if imported)", "country_of_origin"),
    "Rule 6(1)(b)": ("Common / Generic Name", "common_name"),
    "Rule 6(1)(c)": ("Net Quantity", "net_quantity"),
    "Rule 6(1)(d)": ("Manufacturing / Packing Date", "manufacturing_date"),
    "Rule 6(1)(da)": ("Best-before / Use-by", "best_before"),
    "Rule 6(1)(e)": ("Maximum Retail Price (MRP)", "mrp"),
    "Rule 6(1)(f)": ("Consumer Care Details", "consumer_care"),
    "Rule 6(11)": ("Unit Sale Price", "unit_sale_price"),
}

EXCLUDED_FROM_OTHER_RULES = {"Rule 7", "Rule 8", "Rule 9"}


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _status(value):
    value = _text(value).upper()
    if value in {"PASS", "COMPLIANT"}:
        return "PASS"
    if value in {"FAIL", "NON_COMPLIANT", "ERROR"}:
        return "FAIL"
    if value in {"N/A", "NOT_APPLICABLE", "NOT APPLICABLE"}:
        return "N/A"
    return "REVIEW"


def _status_label(status):
    return {"PASS": "PASS", "FAIL": "FAIL", "REVIEW": "REVIEW", "N/A": "N/A"}.get(status, "REVIEW")


def _source(result):
    info = result.get("additional_information") or {}
    return _text(info.get("extraction_source")) or "GEMINI_VLM"


def _classification(result):
    return (result.get("additional_information") or {}).get("classification") or {}


def _applicability(result):
    info = result.get("additional_information") or {}
    classification = _classification(result)
    summary = _text(info.get("applicability_summary"))

    if classification.get("rule3_exclusion_candidate"):
        state = "CONDITIONAL / REVIEW"
        reason = "; ".join(classification.get("rule3_exclusion_reasons") or []) or "Rule 3 applicability needs verification."
    elif classification.get("rule26_exemption_candidate"):
        state = "CONDITIONAL / REVIEW"
        reason = str(classification.get("rule26_exemption_candidate"))
    elif classification.get("prepackaged_candidate"):
        state = "IN-SCOPE CANDIDATE"
        reason = "Package is being treated as a pre-packaged commodity for image-level screening."
    else:
        state = summary or "REVIEW"
        reason = "Applicability could not be established conclusively from the supplied package evidence."

    return {
        "state": state,
        "category": _text(classification.get("product_category")) or "UNKNOWN",
        "confidence": classification.get("product_category_confidence") or 0,
        "context": (
            "EXPORT" if classification.get("export") else
            "WHOLESALE" if classification.get("wholesale") else
            "RETAIL / PRE-PACKAGED"
        ),
        "reasons": classification.get("category_evidence") or [],
        "reason": reason,
        "rule3": next((x for x in info.get("applicability_checks", []) if x.get("rule") == "Rule 3"), None),
        "rule26": next((x for x in info.get("applicability_checks", []) if x.get("rule") == "Rule 26"), None),
    }


def _visual_summary(result):
    """Normalize the single global readability/placement assessment."""
    visual_assessment = result.get("visual_assessment") or {}
    visual = (result.get("vlm") or {}).get("visual_analysis") or {}

    readability = (
        visual_assessment.get("overall_readability")
        or visual.get("overall_readability")
        or visual.get("mandatory_text_readability")
        or "UNKNOWN"
    )
    placement = (
        visual_assessment.get("declaration_placement")
        or visual.get("declaration_placement")
        or "UNKNOWN"
    )

    r = _text(readability).upper()
    p = _text(placement).upper()
    if r in {"ILLEGIBLE", "UNREADABLE", "NOT_VISIBLE", "OBSCURED", "BLURRED", "FAIL"} or p in {"NOT_VISIBLE", "OBSCURED", "FAIL"}:
        status = "FAIL"
    elif r in {"UNKNOWN", "NOT_ASSESSED", "UNDETERMINED", ""} or p in {"UNKNOWN", "NOT_ASSESSED", "UNDETERMINED", ""}:
        status = "REVIEW"
    elif r in {"CLEAR", "CLEARLY_VISIBLE", "READABLE", "GOOD", "HIGH"} and p in {"CLEAR", "CLEARLY_VISIBLE", "GOOD", "COMPLIANT", "PASS"}:
        status = "PASS"
    else:
        status = "REVIEW"

    return {
        "readability": _text(readability) or "UNKNOWN",
        "placement": _text(placement) or "UNKNOWN",
        "status": status,
        "status_label": _status_label(status),
        "reason": f"Overall readability: {_text(readability) or 'UNKNOWN'}. Overall placement: {_text(placement) or 'UNKNOWN'}.",
    }


def _canonical_field(field):
    field = _text(field).lower()
    return FONT_CANONICAL.get(field, field)


def _build_final_font_map(result):
    """Collapse all calibrated view measurements into one declaration result."""
    font_items = (result.get("font_measurement") or {}).get("items") or []
    grouped = {}
    for item in font_items:
        field = _canonical_field(item.get("field"))
        if not field or item.get("lettering_height_mm") is None:
            continue
        try:
            mm = float(item.get("lettering_height_mm"))
        except (TypeError, ValueError):
            continue
        grouped.setdefault(field, []).append(item)

    final = {}
    for field, items in grouped.items():
        heights = [float(x["lettering_height_mm"]) for x in items]
        threshold_values = []
        for x in items:
            value = x.get("rule7_minimum_mm")
            if value is not None:
                try:
                    threshold_values.append(float(value))
                except (TypeError, ValueError):
                    pass

        final_height = round(median(heights), 3)
        minimum = round(median(threshold_values), 3) if threshold_values else None

        raw_statuses = {_text(x.get("rule7_status")).upper() for x in items}
        if minimum is None:
            rule7_status = "REVIEW"
            status_reason = "No Rule 7 minimum could be assigned from the available PDP/applicability evidence."
        elif "FAIL" in raw_statuses:
            rule7_status = "FAIL"
            status_reason = "At least one calibrated view produced a Rule 7 failure. Review the view evidence before enforcement action."
        elif "REVIEW_REQUIRED" in raw_statuses or "REVIEW" in raw_statuses:
            rule7_status = "REVIEW"
            status_reason = "One or more calibrated views require review; the final height is shown as a screening measurement."
        elif final_height >= minimum:
            rule7_status = "PASS"
            status_reason = f"Final measured height {final_height:.3f} mm meets the {minimum:.3f} mm Rule 7 minimum."
        else:
            rule7_status = "FAIL"
            status_reason = f"Final measured height {final_height:.3f} mm is below the {minimum:.3f} mm Rule 7 minimum."

        views = []
        for item in items:
            views.append({
                "view": item.get("image_index") or item.get("view"),
                "height_mm": item.get("lettering_height_mm"),
                "minimum_mm": item.get("rule7_minimum_mm"),
                "confidence": item.get("measurement_confidence", "UNKNOWN"),
                "measurement_status": _text(item.get("status")) or "REVIEW_REQUIRED",
                "rule7_status": _text(item.get("rule7_status")) or "REVIEW_REQUIRED",
                "reason": item.get("reason") or item.get("rule7_reason") or "",
                "glyphs": item.get("glyph_details") or [],
                "text": item.get("text"),
            })

        final[field] = {
            "height_mm": final_height,
            "minimum_mm": minimum,
            "rule7_status": rule7_status,
            "rule7_status_label": _status_label(rule7_status),
            "status_reason": status_reason,
            "view_count": len(heights),
            "views": views,
            "method": "Median of calibrated view measurements",
        }
    return final


def _declaration_rows(result):
    checks = result.get("rule_checks") or []
    final_font = _build_final_font_map(result)
    rows = []

    for check in checks:
        rule = _text(check.get("rule"))
        if rule not in DECLARATION_RULES:
            continue
        # N/A declarations are not applicable and therefore do not belong in
        # the applicable-declaration table.
        status = _status(check.get("status"))
        if status == "N/A":
            continue

        label, canonical = DECLARATION_RULES[rule]
        value = check.get("detected_value")
        # M = mandatory Rule 6 declaration; A/M = conditionally applicable mandatory declaration.
        badge = "A/M" if rule in {"Rule 6(1)(aa)", "Rule 6(1)(da)", "Rule 6(11)"} else "M"
        missing = value is None or _text(value) == ""
        rows.append({
            "id": rule,
            "label": label,
            "value": value,
            "mandatory_badge": badge,
            "missing": missing,
            "evidence": check.get("reason") or "No explanation provided.",
            "rule": rule,
            "status": status,
            "status_label": _status_label(status),
            "confidence": check.get("confidence"),
            "applicability": _text(check.get("applicability")) or "APPLICABLE",
            "font": final_font.get(canonical),
        })

    # Avoid duplicate declaration rows if a future registry accidentally emits
    # the same Rule 6 sub-rule twice.
    unique = []
    seen = set()
    for row in rows:
        if row["rule"] in seen:
            continue
        seen.add(row["rule"])
        unique.append(row)
    return unique


def _rule_rows(result):
    rows = []
    for check in result.get("rule_checks") or []:
        status = _status(check.get("status"))
        rows.append({
            "rule": _text(check.get("rule")) or "—",
            "requirement": _text(check.get("requirement")) or "No requirement description available.",
            "value": check.get("detected_value"),
            "applicability": _text(check.get("applicability")) or "—",
            "status": status,
            "status_label": _status_label(status),
            "reason": _text(check.get("reason")) or "No explanation provided.",
            "confidence": check.get("confidence"),
        })
    return rows


def _views(result):
    raw = result.get("images") or []
    if raw:
        return raw
    return [{
        "index": 1,
        "image_path": (result.get("vlm") or {}).get("source_image") or "",
        "extraction_source": _source(result),
        "calibration": result.get("calibration") or {},
        "annotation": result.get("annotation") or {},
        "font_measurement": result.get("font_measurement") or {},
    }]


def _other_rules(rows):
    return [
        row for row in rows
        if not row["rule"].startswith("Rule 6") and row["rule"] not in EXCLUDED_FROM_OTHER_RULES
    ]


def _font_summary(declarations):
    applicable = len(declarations)
    measured = sum(1 for row in declarations if row.get("font"))
    passed = sum(1 for row in declarations if (row.get("font") or {}).get("rule7_status") == "PASS")
    failed = sum(1 for row in declarations if (row.get("font") or {}).get("rule7_status") == "FAIL")
    review = max(0, measured - passed - failed) + (applicable - measured)
    return {
        "applicable": applicable,
        "measured": measured,
        "passed": passed,
        "failed": failed,
        "review": review,
        "label": f"{passed}/{applicable}" if applicable else "0/0",
        "state": "PASS" if applicable and passed == applicable else ("FAIL" if failed else "REVIEW"),
    }


def _font_overall_note(font_summary):
    if not font_summary["applicable"]:
        return "No applicable declaration was available for Rule 7 lettering measurement."
    if font_summary["failed"]:
        return "One or more declarations are below the measured Rule 7 minimum or have a view-level failure."
    if font_summary["review"]:
        return "Some declaration measurements require review because calibrated/quality or statutory-threshold evidence is incomplete."
    return "All measured applicable declarations met their assigned Rule 7 minimum in the available calibrated views."


def build_result_view_model(result, scan=None):
    result = result or {}
    declarations = _declaration_rows(result)
    rules = _rule_rows(result)
    other_rules = _other_rules(rules)
    visual_summary = _visual_summary(result)
    font_summary = _font_summary(declarations)
    counts = Counter(row["status"] for row in rules)
    warnings = result.get("warning_messages") or result.get("warnings") or []
    source = _source(result)
    applicability = _applicability(result)

    verdict = _status(result.get("status"))
    verdict_label = {
        "PASS": "COMPLIANT",
        "FAIL": "NON-COMPLIANT",
        "REVIEW": "COMPLIANT · REVIEW ITEMS",
    }.get(verdict, "REVIEW")

    failed_declarations = sum(1 for r in declarations if r["status"] == "FAIL")
    missing_declarations = sum(1 for r in declarations if r.get("missing"))
    metrics = [
        {"label": "Applicable declarations", "value": str(len(declarations))},
        {"label": "Failed declarations", "value": str(failed_declarations)},
        {"label": "Missing declarations", "value": str(missing_declarations)},
        {"label": "Views analysed", "value": str(len(_views(result)))},
    ]

    info = result.get("additional_information") or {}
    technical = {
        "engine": "Primary visual analysis with local fallback",
        "extraction_source": source,
        "image_count": len(_views(result)),
        "rules_evaluated": len(rules),
        "rules_registry_total": info.get("rule_registry_total"),
        "rules_version": info.get("rules_version") or info.get("rule_registry_version"),
        "ocr_used": bool(info.get("ocr_used")) or source == "OCR_FALLBACK",
        "decision_source": info.get("decision_source"),
    }

    return {
        "header": {
            "product": (scan or {}).get("product_label") or (result.get("vlm") or {}).get("product_name") or "Unlabelled package",
            "verdict": verdict,
            "verdict_label": verdict_label,
            "scan_id": (scan or {}).get("id"),
            "created_at": (scan or {}).get("created_at"),
            "source": source,
            "evidence_score": result.get("score", 0),
            "declaration_coverage": result.get("declaration_coverage", 0),
        },
        "metrics": metrics,
        "applicability": applicability,
        "declarations": declarations,
        "font_summary": font_summary,
        "font_overall_note": _font_overall_note(font_summary),
        "visual_summary": visual_summary,
        "views": _views(result),
        "rules": rules,
        "other_rules": other_rules,
        "findings": {
            "pass": [x for x in declarations if x["status"] == "PASS"],
            "fail": [x for x in declarations if x["status"] == "FAIL"],
            "review": [x for x in declarations if x["status"] == "REVIEW"],
            "warnings": warnings,
        },
        "technical": technical,
        "raw_vlm": result.get("vlm") or {},
        "errors": result.get("vlm_error") or "",
        "annotation_errors": [
            {"index": v.get("index"), "error": (v.get("annotation") or {}).get("error")}
            for v in _views(result) if (v.get("annotation") or {}).get("error")
        ],
        "calibration": result.get("calibration") or {},
        "result": result,
    }


# Kept for compatibility with compliance_engine.py.
def evaluate_presentation(vlm):
    """Return the existing image-level Rule 7/8/9 screening checks."""
    import re

    visual = vlm.get("visual_analysis") or {}
    quantity = _text(vlm.get("net_quantity"))
    placement = _text(visual.get("declaration_placement"))
    readability = _text(visual.get("mandatory_text_readability"))
    font_issue = bool(visual.get("possible_font_size_issue"))
    checks = []

    if font_issue:
        r7_status = "REVIEW_REQUIRED"
        r7_reason = "A possible lettering-size problem was visually flagged; exact statutory height requires physical scale/reference."
    else:
        r7_status = "REVIEW_REQUIRED"
        r7_reason = "An ordinary image cannot prove statutory lettering height in millimetres."
    checks.append({"rule": "Rule 7", "status": r7_status, "detected_value": "possible issue" if font_issue else "no conclusive issue", "reason": r7_reason})

    if placement.lower() in {"clear", "good", "compliant", "pass"}:
        r8_status, r8_reason = "PASS", "Declaration placement was visually assessed as clear."
    else:
        r8_status, r8_reason = "REVIEW_REQUIRED", "Declaration placement was not established confidently enough for a conclusive legal determination."
    checks.append({"rule": "Rule 8", "status": r8_status, "detected_value": placement or "UNKNOWN", "reason": r8_reason})

    if readability.lower() in {"clear", "good", "readable", "high"}:
        r9_status, r9_reason = "PASS", "Mandatory text was visually assessed as readable."
    elif readability.lower() in {"poor", "illegible", "unreadable"}:
        r9_status, r9_reason = "FAIL", "Mandatory text was visually assessed as difficult or impossible to read."
    else:
        r9_status, r9_reason = "REVIEW_REQUIRED", "Readability was not established with sufficient confidence."
    checks.append({"rule": "Rule 9", "status": r9_status, "detected_value": readability or "UNKNOWN", "reason": r9_reason})

    if not quantity:
        checks.append({"rule": "Rule 11", "status": "FAIL", "detected_value": None, "reason": "Net quantity declaration is missing."})
        checks.append({"rule": "Rule 12", "status": "REVIEW_REQUIRED", "detected_value": None, "reason": "Quantity-related qualification/dimension provisions cannot be assessed without the commodity classification."})
        checks.append({"rule": "Rule 13", "status": "FAIL", "detected_value": None, "reason": "No quantity/unit statement was detected."})
    else:
        has_unit = bool(re.search(r"(?:\d+(?:\.\d+)?)\s*(kg|g|mg|l|litre|liter|ml|m|cm|mm|number|no\.?|nos?\.?|pcs?|pieces?)\b", quantity, re.I))
        checks.append({"rule": "Rule 11", "status": "PASS" if has_unit else "REVIEW_REQUIRED", "detected_value": quantity, "reason": "Quantity declaration is present with a recognizable unit." if has_unit else "Quantity exists but its unit could not be normalized confidently."})
        checks.append({"rule": "Rule 12", "status": "REVIEW_REQUIRED", "detected_value": quantity, "reason": "Commodity-specific quantity qualification/dimension requirements require classification and the applicable provision."})
        checks.append({"rule": "Rule 13", "status": "PASS" if has_unit else "REVIEW_REQUIRED", "detected_value": quantity, "reason": "A recognizable unit/number expression was detected." if has_unit else "Unit expression requires review."})
    return checks
