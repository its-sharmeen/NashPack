"""Scope and applicability classification for SIH26034.

The classifier is intentionally conservative: a weak signal creates a review
rather than silently declaring a package exempt or non-applicable.
"""

from .rule_registry import RULE_REGISTRY


def _truth(v):
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"true", "yes", "y", "1", "imported"}


def _text(v):
    return str(v or "").strip().lower()


def _category(vlm):
    value=_text(vlm.get("product_category"))
    allowed={
        "food","electronic","garment_textile","cosmetic_personal_care",
        "household_cleaning","toiletry","stationery","toy","footwear",
        "medical_device","drug","agricultural","cement_fertilizer","other","unknown"
    }
    if value in allowed and value != "unknown":
        return value
    # Backward-compatible visual/evidence fallback for older VLM responses
    # and conservative UNKNOWN VLM outputs.
    text=" ".join([
        _text(vlm.get("common_name")), _text(vlm.get("product_name")),
        _text(vlm.get("manufacturer_name")),
        " ".join(_text(x) for x in (vlm.get("evidence") or []) if x)
    ])
    food_terms=["ghee","milk","dairy","rice","atta","flour","dal","salt","sugar","biscuit","bread","snack","chips","juice","tea","coffee","spice","masala","peanut","food","ingredients","nutrition","fssai"]
    if vlm.get("fssai_numbers") or any(k in text for k in food_terms):
        return "food"
    return "unknown"


def classify_package(vlm):
    product = _text(vlm.get("common_name") or vlm.get("product_name"))
    quantity = _text(vlm.get("net_quantity"))
    category = _category(vlm)
    category_conf = float(vlm.get("product_category_confidence") or 0)

    flags = {
        "prepackaged_candidate": True,
        "imported": _truth(vlm.get("is_imported")),
        "industrial_or_institutional": _truth(vlm.get("industrial_or_institutional")),
        "large_agri_cement_fertilizer": _truth(vlm.get("agricultural_farm_produce_or_cement_fertilizer_over_50kg")),
        "small_package_candidate": _truth(vlm.get("exempt_small_package")),
        "restaurant_fast_food": _truth(vlm.get("restaurant_or_hotel_fast_food")),
        "medical_device_or_drug": _truth(vlm.get("medical_device_or_drug")),
        "wholesale": _truth(vlm.get("wholesale_package")),
        "export": _truth(vlm.get("export_package")),
        "electronic": category == "electronic",
        "garment_or_hosiery": category == "garment_textile",
        "food": category == "food",
        "dimension_sensitive": _truth(vlm.get("dimensions_relevant")),
        "multi_piece": _truth(vlm.get("combination_or_multi_piece_package")),
        "advertising_context": _truth(vlm.get("advertising_context")),
    }

    # Rule 3 exclusions must be explicit enough to justify a scope decision.
    exclusions = []
    if flags["industrial_or_institutional"]:
        exclusions.append("industrial/institutional consumer")
    if flags["large_agri_cement_fertilizer"]:
        exclusions.append("specified large agricultural/cement/fertilizer package")
    # Do not infer a blanket quantity exclusion from the printed net quantity.
    # Current DoCA guidance distinguishes commodity/category-specific applicability;
    # the VLM must explicitly classify the agricultural/farm-produce/cement/fertilizer
    # over-50-kg case before Rule 3 is treated as an exclusion candidate.

    flags["product_category"] = category.upper()
    flags["product_category_confidence"] = category_conf
    flags["category_evidence"] = vlm.get("category_evidence") or []
    flags["rule3_exclusion_candidate"] = bool(exclusions)
    flags["rule3_exclusion_reasons"] = exclusions

    if flags["restaurant_fast_food"]:
        flags["rule26_exemption_candidate"] = "fast-food package packed by restaurant/hotel"
    elif flags["small_package_candidate"]:
        flags["rule26_exemption_candidate"] = "small package"
    elif flags["garment_or_hosiery"] and _truth(vlm.get("sold_loose_or_open")):
        flags["rule26_exemption_candidate"] = "garment/hosiery sold loose/open"
    elif flags["medical_device_or_drug"]:
        flags["rule26_exemption_candidate"] = "medical-device special regime; verify Medical Devices Rules, 2017"
    else:
        flags["rule26_exemption_candidate"] = None

    return flags


def evaluate_applicability(vlm):
    flags = classify_package(vlm)
    rows = []

    if flags["rule3_exclusion_candidate"]:
        rows.append({
            "rule": "Rule 3",
            "status": "REVIEW_REQUIRED",
            "applicability": "CONDITIONAL",
            "reason": "Possible Rule 3 exclusion detected: " + "; ".join(flags["rule3_exclusion_reasons"]),
        })
    else:
        rows.append({
            "rule": "Rule 3",
            "status": "PASS",
            "applicability": "APPLICABLE_CANDIDATE",
            "reason": "No Rule 3 exclusion was confidently established from the supplied package data.",
        })

    rows.append({
        "rule": "Rule 26",
        "status": "REVIEW_REQUIRED" if flags["rule26_exemption_candidate"] else "NOT_APPLICABLE",
        "applicability": "CONDITIONAL" if flags["rule26_exemption_candidate"] else "NO_OBVIOUS_EXEMPTION",
        "reason": ("Possible exemption: " + str(flags["rule26_exemption_candidate"])) if flags["rule26_exemption_candidate"] else "No obvious Rule 26 exemption signal was detected.",
    })

    return {"classification": flags, "checks": rows}


def registry_metadata():
    return {
        "total_numbered_rules": len(RULE_REGISTRY),
        "registry_ids": [r["id"] for r in RULE_REGISTRY],
    }
