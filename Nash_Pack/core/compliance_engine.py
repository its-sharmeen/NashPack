"""
SIH26034 - Legal Metrology Compliance Engine
VLM-only compliance engine.

IMPORTANT:
- OCR is intentionally disabled.
- Gemini VLM is the source of package observations.
- UNKNOWN is NOT treated as FAIL.
- Image-unprovable requirements become REVIEW_REQUIRED.
- Physical/contextual requirements are never falsely marked PASS.
"""

from datetime import datetime
import re

from .applicability_engine import evaluate_applicability
from .declaration_engine import validate_declarations
from .presentation_engine import evaluate_presentation
from .rule_registry import RULE_REGISTRY


RULES_VERSION = "Legal Metrology (Packaged Commodities) Rules, 2011 — prototype registry aligned to DoCA amendments through May 2026; image-checkable vs contextual/physical checks are separated"


# ============================================================
# BASIC HELPERS
# ============================================================

def _present(value):
    """
    Returns True only when a meaningful value is available.
    """
    if value is None:
        return False

    if isinstance(value, str):
        value = value.strip().lower()

        if value in {
            "",
            "none",
            "null",
            "n/a",
            "na",
            "not available",
            "not detected",
            "unknown",
            "not visible",
            "missing",
        }:
            return False

    return True


def _clear(value):
    """
    Visual status helper.
    """
    if value is None:
        return False

    return str(value).strip().upper() in {
        "CLEAR",
        "CLEARLY_VISIBLE",
        "READABLE",
        "GOOD",
        "YES",
    }


def _unknown(value):
    if value is None:
        return True

    return str(value).strip().upper() in {
        "",
        "UNKNOWN",
        "NOT_ASSESSED",
        "UNDETERMINED",
        "N/A",
        "NA",
    }


def _fail_visual(value):
    if value is None:
        return False

    return str(value).strip().upper() in {
        "NOT_VISIBLE",
        "OBSCURED",
        "BLURRED",
        "ILLEGIBLE",
        "UNREADABLE",
        "FAIL",
    }


def _norm(value):
    if value is None:
        return ""

    return str(value).strip().lower()


def _rule(
    rule,
    requirement,
    detected,
    status,
    reason,
    applicability="APPLICABLE",
    confidence="HIGH",
):
    return {
        "rule": rule,
        "requirement": requirement,
        "detected_value": detected,
        "applicability": applicability,
        "status": status,
        "reason": reason,
        "confidence": confidence,
    }


def _is_true(value):
    if isinstance(value, bool):
        return value

    return _norm(value) in {
        "true",
        "yes",
        "y",
        "1",
        "applicable",
        "imported",
    }


# ============================================================
# COMMODITY / APPLICABILITY HELPERS
# ============================================================

def _is_imported(vlm):
    return _is_true(vlm.get("is_imported"))


def _is_industrial_or_institutional(vlm):
    return _is_true(vlm.get("industrial_or_institutional"))


def _is_agri_cement_fertilizer_large(vlm):
    return _is_true(
        vlm.get(
            "agricultural_farm_produce_or_cement_fertilizer_over_50kg"
        )
    )


def _is_small_exempt_package(vlm):
    return _is_true(vlm.get("exempt_small_package"))


def _is_fast_food(vlm):
    return _is_true(vlm.get("restaurant_or_hotel_fast_food"))


def _is_medical_device_or_drug(vlm):
    return _is_true(vlm.get("medical_device_or_drug"))


def _is_wholesale(vlm):
    return _is_true(vlm.get("wholesale_package"))


def _is_export(vlm):
    return _is_true(vlm.get("export_package"))


def _is_combo_or_multi_piece(vlm):
    return _is_true(
        vlm.get("combination_or_multi_piece_package")
    )


def _is_dimension_relevant(vlm):
    """
    We deliberately do not assume dimensions are relevant.
    Gemini may classify the commodity as dimension-sensitive.
    """

    value = vlm.get("dimensions_relevant")

    if value is not None:
        return _is_true(value)

    product = _norm(
        vlm.get("common_name")
        or vlm.get("product_name")
    )

    keywords = [
        "cloth",
        "fabric",
        "bedsheet",
        "bed sheet",
        "saree",
        "dhoti",
        "towel",
        "napkin",
        "pillow cover",
        "table cloth",
        "aluminium foil",
        "facial tissue",
        "toilet paper",
        "wax paper",
        "sheet",
        "container",
        "pipe",
        "rope",
        "wire",
        "cable",
    ]

    return any(k in product for k in keywords)


# ============================================================
# VISUAL ANALYSIS
# ============================================================

def _visual_checks(vlm):
    visual = vlm.get("visual_analysis") or {}

    result = []

    fields = [
        (
            "Manufacturer / Packer Details",
            visual.get("manufacturer_visibility"),
            visual.get("mandatory_text_readability"),
            visual.get("declaration_placement"),
        ),
        (
            "Common / Generic Product Name",
            visual.get("product_name_visibility")
            or visual.get("common_name_visibility"),
            visual.get("mandatory_text_readability"),
            visual.get("declaration_placement"),
        ),
        (
            "Net Quantity",
            visual.get("quantity_visibility"),
            visual.get("mandatory_text_readability"),
            visual.get("declaration_placement"),
        ),
        (
            "Maximum Retail Price (MRP)",
            visual.get("mrp_visibility"),
            visual.get("mandatory_text_readability"),
            visual.get("declaration_placement"),
        ),
        (
            "Manufacturing Date",
            visual.get("date_visibility"),
            visual.get("mandatory_text_readability"),
            visual.get("declaration_placement"),
        ),
        (
            "Consumer Care Details",
            visual.get("consumer_care_visibility"),
            visual.get("mandatory_text_readability"),
            visual.get("declaration_placement"),
        ),
    ]

    for name, visibility, readability, placement in fields:

        statuses = [
            str(visibility or "").upper(),
            str(readability or "").upper(),
            str(placement or "").upper(),
        ]

        # ----------------------------------------------------
        # HARD FAILURE
        # ----------------------------------------------------
        if (
            _fail_visual(visibility)
            or _fail_visual(readability)
        ):
            status = "FAIL"

            reason = (
                f"Visual screening failure — "
                f"visibility: {visibility or 'UNKNOWN'}, "
                f"readability: {readability or 'UNKNOWN'}"
            )

        # ----------------------------------------------------
        # PASS
        # ----------------------------------------------------
        elif _clear(visibility) and _clear(readability):

            # Placement UNKNOWN does NOT fail the declaration.
            if _unknown(placement):
                status = "REVIEW_REQUIRED"

                reason = (
                    "Declaration is visible and readable, "
                    "but exact statutory placement cannot be "
                    "conclusively established from the image."
                )
            elif _clear(placement):
                status = "PASS"

                reason = (
                    "Declaration is visually clear, readable "
                    "and placement is assessed as clear."
                )
            else:
                status = "REVIEW_REQUIRED"

                reason = (
                    "Declaration is visible and readable, "
                    "but placement requires manual verification."
                )

        # ----------------------------------------------------
        # UNKNOWN / PARTIAL
        # ----------------------------------------------------
        else:
            status = "REVIEW_REQUIRED"

            reason = (
                f"Visual assessment is inconclusive — "
                f"visibility: {visibility or 'UNKNOWN'}, "
                f"readability: {readability or 'UNKNOWN'}, "
                f"placement: {placement or 'UNKNOWN'}"
            )

        result.append(
            {
                "item": name,
                "visibility": visibility or "UNKNOWN",
                "readability": readability or "UNKNOWN",
                "placement": placement or "UNKNOWN",
                "status": status,
                "finding": reason,
            }
        )

    return result


def _visual_score(visual_checks):
    """
    Scoring:
        PASS              = 100
        REVIEW_REQUIRED   = 50
        FAIL              = 0

    This prevents UNKNOWN from destroying the score.
    """

    if not visual_checks:
        return 0

    points = 0

    for item in visual_checks:
        status = item.get("status")

        if status == "PASS":
            points += 100

        elif status == "REVIEW_REQUIRED":
            points += 50

        elif status == "FAIL":
            points += 0

    return round(points / len(visual_checks))


# ============================================================
# RULE ENGINE
# ============================================================

def _build_rules(vlm):

    rules = []

    imported = _is_imported(vlm)
    industrial = _is_industrial_or_institutional(vlm)
    large_agri = _is_agri_cement_fertilizer_large(vlm)
    small_exempt = _is_small_exempt_package(vlm)
    fast_food = _is_fast_food(vlm)
    wholesale = _is_wholesale(vlm)
    export_package = _is_export(vlm)

    # --------------------------------------------------------
    # RULE 3 - APPLICABILITY
    # --------------------------------------------------------

    if industrial or large_agri:
        rules.append(
            _rule(
                "Rule 3",
                "Determine whether Chapter II retail-package provisions apply.",
                "Package context indicates an excluded category.",
                "REVIEW_REQUIRED",
                "The Rules contain exclusions for certain industrial/institutional and specified large packages. Context should be verified.",
                "CONDITIONAL",
                "MEDIUM",
            )
        )

    else:
        rules.append(
            _rule(
                "Rule 3",
                "Determine applicability of packaged-commodity requirements.",
                "Appears to be a retail pre-packaged commodity.",
                "PASS",
                "No visible evidence indicates an obvious Rule 3 exclusion.",
                "APPLICABLE",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 4 - PREPACKING / SALE
    # --------------------------------------------------------

    if fast_food:
        rules.append(
            _rule(
                "Rule 4",
                "Pre-packaged commodity requirements.",
                "Restaurant/hotel fast-food context detected.",
                "N/A",
                "Fast food packed by a restaurant or hotel may fall under an exemption.",
                "EXEMPTION_POSSIBLE",
                "MEDIUM",
            )
        )
    else:
        rules.append(
            _rule(
                "Rule 4",
                "Commodity must comply with applicable packaged-commodity provisions.",
                "Pre-packaged commodity indicated.",
                "PASS",
                "Package appears to be a pre-packaged commodity.",
                "APPLICABLE",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 6(1)(a)
    # --------------------------------------------------------

    manufacturer = vlm.get("manufacturer_name")
    manufacturer_address = vlm.get("manufacturer_address")
    importer = vlm.get("importer_name")
    importer_address = vlm.get("importer_address")

    manufacturer_ok = _present(manufacturer) and _present(manufacturer_address)
    importer_ok = (not imported) or (_present(importer) and _present(importer_address))

    if manufacturer_ok and importer_ok:
        detected = f"{manufacturer}; {manufacturer_address}"
        if imported:
            detected += f" | Importer: {importer}; {importer_address}"
        rules.append(
            _rule(
                "Rule 6(1)(a)",
                "Name and address of manufacturer/packer/importer.",
                detected,
                "PASS",
                "Required manufacturer/packer details were detected" + (" and importer details were detected for an imported package." if imported else "."),
            )
        )
    else:
        rules.append(
            _rule(
                "Rule 6(1)(a)",
                "Name and address of manufacturer/packer/importer.",
                manufacturer or manufacturer_address or importer or importer_address or None,
                "FAIL",
                "Required manufacturer/packer details were not complete" + (" or importer details were missing for an imported package." if imported else "."),
            )
        )

    # --------------------------------------------------------
    # RULE 6(1)(b) - COUNTRY OF ORIGIN
    # --------------------------------------------------------

    if imported:

        country = vlm.get("country_of_origin")

        if _present(country):
            rules.append(
                _rule(
                    "Rule 6(1)(aa)",
                    "Country of origin for imported product.",
                    country,
                    "PASS",
                    "Country of origin was detected for an imported product.",
                )
            )
        else:
            rules.append(
                _rule(
                    "Rule 6(1)(aa)",
                    "Country of origin for imported product.",
                    None,
                    "FAIL",
                    "Imported product detected but country of origin was not found.",
                )
            )

    else:
        rules.append(
            _rule(
                "Rule 6(1)(aa)",
                "Country of origin for imported product.",
                vlm.get("country_of_origin"),
                "N/A",
                "Product is not identified as imported.",
                "NOT_APPLICABLE",
            )
        )

    # --------------------------------------------------------
    # RULE 6(1)(c) - COMMON / GENERIC NAME
    # --------------------------------------------------------

    common_name = (
        vlm.get("common_name")
        or vlm.get("product_name")
    )

    if _present(common_name):
        rules.append(
            _rule(
                "Rule 6(1)(b)",
                "Common or generic name of commodity.",
                common_name,
                "PASS",
                "A product/common name was detected.",
            )
        )
    else:
        rules.append(
            _rule(
                "Rule 6(1)(b)",
                "Common or generic name of commodity.",
                None,
                "FAIL",
                "Common/generic product name was not detected.",
            )
        )

    # --------------------------------------------------------
    # RULE 6(1)(d) - NET QUANTITY
    # --------------------------------------------------------

    quantity = vlm.get("net_quantity")

    if _present(quantity):
        rules.append(
            _rule(
                "Rule 6(1)(c)",
                "Net quantity in standard unit of weight, measure or number.",
                quantity,
                "PASS",
                "Net quantity declaration was detected.",
            )
        )
    else:
        rules.append(
            _rule(
                "Rule 6(1)(c)",
                "Net quantity in standard unit of weight, measure or number.",
                None,
                "FAIL",
                "Net quantity declaration was not detected.",
            )
        )

    # --------------------------------------------------------
    # RULE 6(1)(e) - MANUFACTURE
    # --------------------------------------------------------

    manufacturing_date = vlm.get("manufacturing_date")

    if _present(manufacturing_date):
        rules.append(
            _rule(
                "Rule 6(1)(d)",
                "Month and year of manufacture/pre-packing/import.",
                manufacturing_date,
                "PASS",
                "Manufacturing date information was detected.",
            )
        )
    else:
        rules.append(
            _rule(
                "Rule 6(1)(d)",
                "Month and year of manufacture/pre-packing/import.",
                None,
                "FAIL",
                "Manufacturing date information was not detected.",
            )
        )

    # --------------------------------------------------------
    # BEST BEFORE / USE BY
    # --------------------------------------------------------

    expiry = vlm.get("expiry_or_best_before")

    if _present(expiry):

        rules.append(
            _rule(
                "Rule 6(1)(da)",
                "Best before/use by information where commodity may become unfit.",
                expiry,
                "PASS",
                "Best-before/use-by information was detected.",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 6(1)(da)",
                "Best before/use by information where applicable.",
                None,
                "REVIEW_REQUIRED",
                "No best-before/use-by information was detected. Applicability depends on the nature of the commodity.",
                "CONDITIONAL",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 6(1)(g) - MRP
    # --------------------------------------------------------

    mrp = vlm.get("mrp")
    inclusive = vlm.get("mrp_inclusive_of_taxes")

    if _present(mrp) and _is_true(inclusive):

        rules.append(
            _rule(
                "Rule 6(1)(e)",
                "Maximum Retail Price inclusive of all taxes.",
                f"₹{mrp}",
                "PASS",
                "MRP was detected and Gemini confirmed that it is inclusive of all taxes.",
            )
        )

    elif _present(mrp):

        rules.append(
            _rule(
                "Rule 6(1)(e)",
                "Maximum Retail Price inclusive of all taxes.",
                mrp,
                "REVIEW_REQUIRED",
                "MRP is visible, but inclusive-of-all-taxes status was not conclusively established.",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 6(1)(e)",
                "Maximum Retail Price inclusive of all taxes.",
                None,
                "FAIL",
                "MRP was not detected.",
            )
        )

    # --------------------------------------------------------
    # RULE 12 - DIMENSIONS
    # --------------------------------------------------------

    if _is_dimension_relevant(vlm):

        dimensions = vlm.get("dimensions")

        if _present(dimensions):
            rules.append(
                _rule(
                    "Rule 12",
                    "Dimensions where relevant to the commodity.",
                    dimensions,
                    "PASS",
                    "Dimensions were detected for a dimension-relevant commodity.",
                )
            )
        else:
            rules.append(
                _rule(
                    "Rule 12",
                    "Dimensions where relevant to the commodity.",
                    None,
                    "FAIL",
                    "Commodity appears dimension-sensitive but dimensions were not detected.",
                )
            )

    else:

        rules.append(
            _rule(
                "Rule 12",
                "Dimensions where relevant to the commodity.",
                vlm.get("dimensions"),
                "N/A",
                "Dimensions do not appear to be relevant to this commodity.",
                "NOT_APPLICABLE",
            )
        )

    # --------------------------------------------------------
    # CONSUMER CARE
    # --------------------------------------------------------

    consumer_care = vlm.get("consumer_care")

    if _present(consumer_care):

        rules.append(
            _rule(
                "Rule 6(1)(f)",
                "Consumer care details.",
                consumer_care,
                "PASS",
                "Consumer care contact information was detected.",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 6(1)(f)",
                "Consumer care details.",
                None,
                "FAIL",
                "Consumer care details were not detected.",
            )
        )

    # --------------------------------------------------------
    # RULE 6(10A) - E-COMMERCE IMPORTED PRODUCT
    # --------------------------------------------------------

    if imported:

        rules.append(
            _rule(
                "Rule 6(10)",
                "Country-of-origin searchable/sortable filter on e-commerce listing.",
                "Cannot be established from package image.",
                "REVIEW_REQUIRED",
                "This requirement concerns an e-commerce product listing rather than the physical package. Current rule effective date is 1 July 2027.",
                "CONTEXT_REQUIRED",
                "HIGH",
            )
        )
    else:

        rules.append(
            _rule(
                "Rule 6(10)",
                "Country-of-origin searchable/sortable filter on e-commerce listing.",
                "Not applicable to non-imported package.",
                "N/A",
                "Package is not identified as imported.",
                "NOT_APPLICABLE",
            )
        )

    # --------------------------------------------------------
    # RULE 7 - PRINCIPAL DISPLAY PANEL / LETTERING
    # --------------------------------------------------------

    visual = vlm.get("visual_analysis") or {}

    font_issue = _is_true(
        visual.get("possible_font_size_issue")
    )

    if font_issue:

        rules.append(
            _rule(
                "Rule 7",
                "Minimum lettering/numeral height on principal display panel.",
                "Possible font-size issue detected.",
                "REVIEW_REQUIRED",
                "Visual model detected a possible lettering-size issue. Exact statutory dimensions require physical scale/reference.",
                "APPLICABLE",
                "MEDIUM",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 7",
                "Minimum lettering/numeral height on principal display panel.",
                "No obvious visual font-size issue detected.",
                "REVIEW_REQUIRED",
                "No obvious issue was detected, but exact statutory lettering/numeral dimensions cannot be proven from an ordinary photograph without scale.",
                "APPLICABLE",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 8 - PLACEMENT
    # --------------------------------------------------------

    placement = visual.get("declaration_placement")

    if _clear(placement):

        rules.append(
            _rule(
                "Rule 8",
                "Required declarations on the principal display panel / prescribed placement.",
                placement,
                "PASS",
                "Gemini assessed declaration placement as clear.",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 8",
                "Required declarations on the principal display panel / prescribed placement.",
                placement or "UNKNOWN",
                "REVIEW_REQUIRED",
                "The package image does not provide sufficiently reliable evidence for a conclusive statutory placement determination.",
                "APPLICABLE",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 11-13 - QUANTITY / UNITS
    # --------------------------------------------------------

    quantity_text = _norm(quantity)

    if not _present(quantity):

        rules.append(
            _rule(
                "Rules 11-13",
                "Quantity declaration and prescribed standard units.",
                None,
                "FAIL",
                "Net quantity is missing.",
            )
        )

    else:

        # Basic unit screening only.
        valid_unit = bool(
            re.search(
                r"(kg|g|mg|l|ml|m|cm|mm|sq|number|unit|pcs|piece|no\.?)",
                quantity_text,
                re.IGNORECASE,
            )
        )

        if valid_unit:

            rules.append(
                _rule(
                    "Rules 11-13",
                    "Quantity declaration and prescribed standard units.",
                    quantity,
                    "PASS",
                    "Quantity contains a recognizable unit. Exact quantity accuracy cannot be established from a photograph.",
                    "APPLICABLE",
                    "MEDIUM",
                )
            )

        else:

            rules.append(
                _rule(
                    "Rules 11-13",
                    "Quantity declaration and prescribed standard units.",
                    quantity,
                    "REVIEW_REQUIRED",
                    "Quantity was detected, but unit compliance requires further verification.",
                    "APPLICABLE",
                    "MEDIUM",
                )
            )

    # --------------------------------------------------------
    # RULE 14-17 - SPECIAL COMMODITIES
    # --------------------------------------------------------

    product = _norm(
        vlm.get("common_name")
        or vlm.get("product_name")
    )

    special_keywords = [
        "bed sheet",
        "bedsheet",
        "saree",
        "dhoti",
        "towel",
        "napkin",
        "pillow cover",
        "table cloth",
        "fabric",
        "foil",
        "facial tissue",
        "toilet paper",
        "wax paper",
        "container",
    ]

    special = any(k in product for k in special_keywords)

    if special:

        dimensions = vlm.get("dimensions")

        if _present(dimensions):

            rules.append(
                _rule(
                    "Rules 14-17",
                    "Special commodity declarations such as number/dimensions where applicable.",
                    dimensions,
                    "PASS",
                    "Potential special-commodity requirement detected and dimensions were found.",
                    "APPLICABLE",
                    "MEDIUM",
                )
            )

        else:

            rules.append(
                _rule(
                    "Rules 14-17",
                    "Special commodity declarations such as number/dimensions where applicable.",
                    None,
                    "REVIEW_REQUIRED",
                    "Commodity may fall under special declaration provisions. Verify applicable rule and dimensions/number.",
                    "CONDITIONAL",
                    "MEDIUM",
                )
            )

    else:

        rules.append(
            _rule(
                "Rules 14-17",
                "Special commodity-specific declarations.",
                "No obvious special commodity category detected.",
                "N/A",
                "No obvious Rule 14-17 commodity category was detected.",
                "NOT_APPLICABLE",
            )
        )

    # --------------------------------------------------------
    # UNIT SALE PRICE
    # --------------------------------------------------------

    unit_sale_price = vlm.get("unit_sale_price")

    if wholesale:

        rules.append(
            _rule(
                "Rule 6(11)",
                "Unit sale price declaration.",
                unit_sale_price,
                "N/A",
                "Unit sale price is not required on wholesale packages.",
                "NOT_APPLICABLE",
            )
        )

    elif _is_combo_or_multi_piece(vlm):

        rules.append(
            _rule(
                "Rule 6(11)",
                "Unit sale price declaration.",
                unit_sale_price,
                "N/A",
                "Package is identified as a combination/group/multi-piece package.",
                "CONDITIONAL",
                "MEDIUM",
            )
        )

    elif _present(unit_sale_price):

        rules.append(
            _rule(
                "Rule 6(11)",
                "Unit sale price declaration.",
                unit_sale_price,
                "PASS",
                "Unit sale price was detected.",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 6(11)",
                "Unit sale price declaration.",
                None,
                "REVIEW_REQUIRED",
                "Unit sale price was not detected. Verify package category and whether the applicable unit-sale-price provision applies.",
                "CONDITIONAL",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 18 - DEALER OBLIGATIONS
    # --------------------------------------------------------

    rules.append(
        _rule(
            "Rule 18",
            "Retailer/dealer obligations relating to sale and MRP.",
            "Cannot be established from package image.",
            "REVIEW_REQUIRED",
            "Dealer behaviour and sale conditions require retail-context evidence.",
            "CONTEXT_REQUIRED",
            "HIGH",
        )
    )

    # --------------------------------------------------------
    # RULE 22 - MPE / ACTUAL QUANTITY
    # --------------------------------------------------------

    rules.append(
        _rule(
            "Rule 22",
            "Maximum permissible error / actual quantity accuracy.",
            quantity,
            "REVIEW_REQUIRED",
            "A photograph can verify the declared quantity but cannot establish actual quantity or maximum permissible error. Physical weighing/measurement is required.",
            "PHYSICAL_TEST_REQUIRED",
            "HIGH",
        )
    )

    # --------------------------------------------------------
    # RULE 23 - DECEPTIVE PACKAGE
    # --------------------------------------------------------

    visual_warnings = visual.get("visual_warnings") or []

    if visual_warnings:

        rules.append(
            _rule(
                "Rule 23",
                "Protection against deceptive packaging.",
                visual_warnings,
                "REVIEW_REQUIRED",
                "Visual warnings may indicate possible deceptive presentation, but legal determination requires contextual assessment.",
                "CONTEXT_REQUIRED",
                "MEDIUM",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 23",
                "Protection against deceptive packaging.",
                "No obvious visual deception detected.",
                "REVIEW_REQUIRED",
                "Absence of an obvious visual issue does not conclusively establish legal compliance with the deceptive-package provision.",
                "CONTEXT_REQUIRED",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 24 - WHOLESALE PACKAGE
    # --------------------------------------------------------

    if wholesale:

        rules.append(
            _rule(
                "Rule 24",
                "Wholesale package declarations.",
                "Wholesale package indicated.",
                "REVIEW_REQUIRED",
                "Wholesale-package declarations require package-category verification.",
                "CONTEXT_REQUIRED",
                "MEDIUM",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 24",
                "Wholesale package declarations.",
                "Retail package indicated.",
                "N/A",
                "No wholesale package was identified.",
                "NOT_APPLICABLE",
            )
        )

    # --------------------------------------------------------
    # RULE 25 - EXPORT
    # --------------------------------------------------------

    if export_package:

        rules.append(
            _rule(
                "Rule 25",
                "Export package restrictions.",
                "Export package indicated.",
                "REVIEW_REQUIRED",
                "Whether an export package was subsequently sold in India requires external/contextual evidence.",
                "CONTEXT_REQUIRED",
                "HIGH",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 25",
                "Export package restrictions.",
                "No export status detected.",
                "N/A",
                "No export-package context was detected.",
                "NOT_APPLICABLE",
            )
        )

    # --------------------------------------------------------
    # RULE 26 - EXEMPTIONS
    # --------------------------------------------------------

    if small_exempt or fast_food or _is_medical_device_or_drug(vlm):

        rules.append(
            _rule(
                "Rule 26",
                "Exemptions from specified packaged-commodity requirements.",
                "Possible exemption category detected.",
                "REVIEW_REQUIRED",
                "An exemption category may apply. Exact exemption eligibility requires commodity/context verification.",
                "CONDITIONAL",
                "MEDIUM",
            )
        )

    else:

        rules.append(
            _rule(
                "Rule 26",
                "Exemptions from specified packaged-commodity requirements.",
                "No obvious exemption detected.",
                "N/A",
                "No Rule 26 exemption signal was detected; exemption provisions are not a defect merely because no exemption applies.",
                "NO_OBVIOUS_EXEMPTION",
                "MEDIUM",
            )
        )

    # --------------------------------------------------------
    # RULE 27 - REGISTRATION
    # --------------------------------------------------------

    rules.append(
        _rule(
            "Rule 27",
            "Registration requirements.",
            "Cannot be verified from package image.",
            "REVIEW_REQUIRED",
            "Registration status must be verified against registration records; it cannot reliably be established from the image alone.",
            "EXTERNAL_RECORD_REQUIRED",
            "HIGH",
        )
    )

    # --------------------------------------------------------
    # RULE 31 - ADVERTISING
    # --------------------------------------------------------

    rules.append(
        _rule(
            "Rule 31",
            "Advertising-related requirements.",
            "No advertising context available.",
            "N/A",
            "The submitted image is a package scan and does not establish advertising context.",
            "NOT_APPLICABLE",
        )
    )

    return rules



def _apply_deterministic_layers(vlm, rule_checks):
    """Overlay deterministic declaration/presentation validation on VLM output.

    VLM extraction remains the evidence source; deterministic validators decide
    whether the extracted evidence has enough structure for a PASS/FAIL.
    """
    rows = list(rule_checks)

    def replace(rule_id, payload):
        nonlocal rows
        replaced = False
        new_rows = []
        for row in rows:
            if row.get("rule") == rule_id:
                if not replaced:
                    updated = row.copy()
                    updated.update(payload)
                    new_rows.append(updated)
                    replaced = True
                # remove duplicate rows for the same rule
            else:
                new_rows.append(row)
        if not replaced:
            new_rows.append(_rule(
                rule_id,
                payload.get("requirement", rule_id),
                payload.get("detected_value"),
                payload.get("status", "REVIEW_REQUIRED"),
                payload.get("reason", "Requirement not assessed."),
                payload.get("applicability", "APPLICABLE"),
                payload.get("confidence", "MEDIUM"),
            ))
        rows = new_rows

    declarations = validate_declarations(vlm)
    for item in declarations["checks"]:
        replace(item["rule"], {
            "status": item["status"],
            "detected_value": item["detected_value"],
            "reason": item["reason"],
            "applicability": "NOT_APPLICABLE" if item["status"] == "N/A" else "APPLICABLE",
            "confidence": "HIGH",
        })

    presentation = evaluate_presentation(vlm)
    for item in presentation:
        replace(item["rule"], {
            "status": item["status"],
            "detected_value": item["detected_value"],
            "reason": item["reason"],
            "applicability": "APPLICABLE",
            "confidence": "MEDIUM",
        })

    # Remove the old grouped quantity row; the report must expose Rules 11, 12, 13 separately.
    rows = [r for r in rows if r.get("rule") != "Rules 11-13"]

    # Rule 6 is a derived summary after deterministic sub-rules have been evaluated.
    sub_ids = {
        "Rule 6(1)(a)", "Rule 6(1)(aa)", "Rule 6(1)(b)", "Rule 6(1)(c)",
        "Rule 6(1)(d)", "Rule 6(1)(da)", "Rule 6(1)(e)", "Rule 6(1)(f)",
        "Rule 6(11)",
    }
    sub = [r for r in rows if r.get("rule") in sub_ids and r.get("status") != "N/A"]
    if any(r.get("status") == "FAIL" for r in sub):
        top_status = "FAIL"
    elif any(r.get("status") == "REVIEW_REQUIRED" for r in sub):
        top_status = "REVIEW_REQUIRED"
    else:
        top_status = "PASS"
    replace("Rule 6", {
        "status": top_status,
        "detected_value": "Derived from applicable Rule 6 sub-rules",
        "reason": "Top-level Rule 6 status is derived from its applicable declaration sub-rules.",
        "applicability": "DERIVED",
        "confidence": "HIGH",
    })

    order = {item["id"]: i for i, item in enumerate(RULE_REGISTRY)}
    return sorted(rows, key=lambda r: order.get(r.get("rule"), 999))


def _augment_complete_rule_register(vlm, rule_checks):
    """Ensure every numbered rule is represented in the final report.

    Existing specialized checks are preserved. Missing provisions are added
    as explicit N/A / REVIEW_REQUIRED records so no rule silently disappears.
    """
    applicability = evaluate_applicability(vlm)
    classification = applicability.get("classification", {})

    existing = {r.get("rule") for r in rule_checks}

    # Replace legacy grouped checks with individual rule rows for serial reporting.
    expanded = []
    for row in rule_checks:
        rid = row.get("rule")
        if rid == "Rules 11-13":
            base = row.copy()
            for sub in ("Rule 11", "Rule 12", "Rule 13"):
                if sub in existing:
                    continue
                item = base.copy()
                item["rule"] = sub
                if sub == "Rule 12" and _is_dimension_relevant(vlm):
                    item["requirement"] = "Manner in which declaration of quantity is expressed; dimensions/number where needed."
                elif sub == "Rule 13":
                    item["requirement"] = "Statement of units of weight, measure or number."
                else:
                    item["requirement"] = "General provisions relating to declaration of quantity."
                expanded.append(item)
            continue
        if rid == "Rules 14-17":
            for sub in ("Rule 14", "Rule 15", "Rule 16", "Rule 17"):
                item = row.copy()
                item["rule"] = sub
                item["requirement"] = {
                    "Rule 14": "Dimensions of specified commodities such as bed-sheets, fabrics, sarees, towels and similar articles.",
                    "Rule 15": "Dimensions/weight where they have a relationship to price.",
                    "Rule 16": "Number of usable sheets and dimensions for sheet commodities.",
                    "Rule 17": "Dimensions/quantity declarations for container-type commodities.",
                }[sub]
                expanded.append(item)
            continue
        expanded.append(row)
    rule_checks = expanded
    existing = {r.get("rule") for r in rule_checks}

    # Applicability rows should use the same engine that powers the UI summary.
    for row in applicability.get("checks", []):
        rid = row["rule"]
        if rid == "Rule 3":
            for old in rule_checks:
                if old.get("rule") == rid:
                    old.update({k: v for k, v in row.items() if k != "rule"})

    def add(rule, requirement, status, reason, applicability_value="NOT_APPLICABLE", confidence="HIGH", detected=None):
        if rule in existing:
            return
        rule_checks.append(_rule(rule, requirement, detected, status, reason, applicability_value, confidence))
        existing.add(rule)

    # Administrative / scope rules: present in the register, but not falsely
    # treated as label failures.
    add("Rule 1", "Short title and commencement.", "N/A", "Administrative provision; it does not create an image-verifiable package declaration.", "ADMINISTRATIVE")
    add("Rule 2", "Definitions used to determine scope and meaning of terms.", "PASS", "Definitions are used by the applicability/classification layer; this is not a package-label defect check.", "CLASSIFICATION")
    add("Rule 5", "Specific commodities to be packed in recommended standard packages.", "N/A", "Rule 5 is omitted in the current consolidated framework; it is retained in the registry for audit completeness.", "OMITTED")
    add("Rule 9", "Declarations must be legible and prominent; MRP and net quantity require prescribed presentation/contrast.", "REVIEW_REQUIRED", "The image can screen legibility and contrast, but a complete Rule 9 legal determination may require closer/manual inspection.", "PARTIAL_IMAGE", "MEDIUM")
    has_name = _present(vlm.get("manufacturer_name") or vlm.get("importer_name"))
    has_address = _present(vlm.get("manufacturer_address") or vlm.get("importer_address"))
    add(
        "Rule 10",
        "Name and complete address of manufacturer/packer/importer.",
        "PASS" if (has_name and has_address) else "REVIEW_REQUIRED",
        "Manufacturer/importer name and address were detected; completeness and any permitted abbreviated-address treatment require verification." if (has_name and has_address) else "A complete name-and-address pair was not established from the available extraction.",
        "IMAGE_AND_CONTEXT",
        "MEDIUM"
    )
    add("Rule 17", "Dimensions/quantity declarations for container-type commodities.", "REVIEW_REQUIRED", "Commodity-specific applicability cannot be established confidently from a generic package image.", "CONDITIONAL", "MEDIUM")
    add("Rule 19", "Inspection of quantity and error at manufacturer/packer premises.", "REVIEW_REQUIRED", "Requires physical sampling and prescribed test procedure; an image cannot perform the inspection.", "PHYSICAL_TEST_REQUIRED")
    add("Rule 20", "Action following inspection findings.", "REVIEW_REQUIRED", "Enforcement action depends on an actual Rule 19 inspection report.", "PHYSICAL_TEST_REQUIRED")
    add("Rule 21", "Inspection at wholesale/retail dealer premises.", "REVIEW_REQUIRED", "Dealer-premises inspection is a physical/contextual enforcement process.", "PHYSICAL_TEST_REQUIRED")
    add("Rule 28", "Registration of shorter address.", "REVIEW_REQUIRED", "Requires registration-record verification; an image cannot establish whether a shorter address is registered.", "EXTERNAL_RECORD_REQUIRED")
    add("Rule 29", "Register of manufacturers and packers.", "REVIEW_REQUIRED", "Requires access to the official registration register.", "EXTERNAL_RECORD_REQUIRED")
    add("Rule 30", "Compilation/circulation of registered manufacturer and packer lists.", "N/A", "Administrative function; not directly testable from a package image.", "ADMINISTRATIVE")
    add("Rule 32", "Fine for contravention of rules.", "N/A", "Penalty provision; it is an enforcement consequence, not an image-level declaration check.", "ADMINISTRATIVE")
    add("Rule 32-A", "Compounding of offences.", "N/A", "Administrative enforcement provision; not an image-level compliance test.", "ADMINISTRATIVE")
    add("Rule 33", "Power to relax.", "REVIEW_REQUIRED", "A relaxation, if any, must be established from an official authorization/record.", "EXTERNAL_RECORD_REQUIRED")
    add("Rule 34", "Repeal and savings.", "N/A", "Savings/repeal provision; it does not create a package-label defect check.", "ADMINISTRATIVE")

    # Rule 6 top-level audit row.
    if "Rule 6" not in existing:
        sub_ids = {"Rule 6(1)(a)", "Rule 6(1)(aa)", "Rule 6(1)(b)", "Rule 6(1)(c)", "Rule 6(1)(d)", "Rule 6(1)(da)", "Rule 6(1)(e)", "Rule 6(1)(f)", "Rule 6(10)", "Rule 6(11)"}
        present_subs = [r for r in rule_checks if r.get("rule") in sub_ids]
        status = "PASS" if present_subs and all(r.get("status") in {"PASS", "N/A"} for r in present_subs) else "REVIEW_REQUIRED"
        add("Rule 6", "Declarations to be made on every package and related e-commerce/unit-sale-price provisions.", status, "Top-level Rule 6 result is derived from its applicable sub-rules; see the serial sub-rule entries below.", "DERIVED", "HIGH")

    # Rule 26 applicability row gets the richer classifier reason.
    for old in rule_checks:
        if old.get("rule") == "Rule 26":
            row = applicability.get("checks", [])[1] if len(applicability.get("checks", [])) > 1 else None
            if row:
                old.update({k: v for k, v in row.items() if k != "rule"})

    # Keep the registry order in the final report. Unknown sub-rules that are
    # intentionally omitted from this label scanner are not silently dropped.
    order = {item["id"]: i for i, item in enumerate(RULE_REGISTRY)}
    return sorted(rule_checks, key=lambda r: order.get(r.get("rule"), 999))

# ============================================================
# DECLARATION SCORE
# ============================================================

def _declaration_score(rule_checks):

    declaration_rules = [
        "Rule 6(1)(a)",
        "Rule 6(1)(b)",
        "Rule 6(1)(c)",
        "Rule 6(1)(d)",
        "Rule 6(1)(e)",
        "Rule 6(1)(f)",
    ]
    # Country of origin is mandatory only for imported products.
    country = next((r for r in rule_checks if r.get("rule") == "Rule 6(1)(aa)"), None)
    if country and country.get("status") != "N/A":
        declaration_rules.append("Rule 6(1)(aa)")

    selected = [
        r for r in rule_checks
        if r.get("rule") in declaration_rules
    ]

    if not selected:
        return 0

    passed = sum(
        1 for r in selected
        if r.get("status") == "PASS"
    )

    return round((passed / len(selected)) * 100)


# ============================================================
# MAIN ENGINE
# ============================================================

def run_compliance_check(vlm_result, vlm_error=None):

    timestamp = datetime.now().isoformat()

    # --------------------------------------------------------
    # GEMINI FAILURE
    # --------------------------------------------------------

    if vlm_error or not isinstance(vlm_result, dict):

        return {
            "status": "ERROR",
            "score": 0,
            "declaration_score": 0,
            "visual_score": 0,
            "mandatory_present": 0,
            "mandatory_missing": [],
            "mandatory_total": 6,
            "warnings": [],
            "warning_messages": [],
            "ocr_confidence": 0,
            "raw_text": "",
            "vlm": vlm_result or {},
            "vlm_error": str(vlm_error or "Invalid Gemini response"),
            "checks": [],
            "rule_checks": [],
            "visual_checks": [],
            "visual_assessment": {},
            "additional_information": {},
            "evidence": [],
            "timestamp": timestamp,
        }

    # --------------------------------------------------------
    # RULES
    # --------------------------------------------------------

    rule_checks = _build_rules(vlm_result)
    rule_checks = _augment_complete_rule_register(vlm_result, rule_checks)
    rule_checks = _apply_deterministic_layers(vlm_result, rule_checks)

    # --------------------------------------------------------
    # VISUAL
    # --------------------------------------------------------

    visual_checks = _visual_checks(vlm_result)

    visual_score = _visual_score(visual_checks)

    # --------------------------------------------------------
    # MANDATORY DECLARATIONS
    # --------------------------------------------------------

    mandatory = [
        (
            "Manufacturer / Packer Details",
            "Rule 6(1)(a)",
        ),
        (
            "Country of Origin (if imported)",
            "Rule 6(1)(aa)",
        ),
        (
            "Common / Generic Product Name",
            "Rule 6(1)(b)",
        ),
        (
            "Net Quantity",
            "Rule 6(1)(c)",
        ),
        (
            "MRP",
            "Rule 6(1)(e)",
        ),
        (
            "Manufacturing Date",
            "Rule 6(1)(d)",
        ),
        (
            "Consumer Care Details",
            "Rule 6(1)(f)",
        ),
    ]

    checks = []
    mandatory_missing = []

    for label, rule_id in mandatory:

        matching = [
            r for r in rule_checks
            if r.get("rule") == rule_id
        ]

        rule_result = matching[0] if matching else None

        if rule_result and rule_result.get("status") == "PASS":

            status = "PASS"

        elif rule_result and rule_result.get("status") == "N/A":

            status = "N/A"

        elif rule_result and rule_result.get("status") == "REVIEW_REQUIRED":

            status = "REVIEW_REQUIRED"

        else:

            status = "FAIL"
            mandatory_missing.append(label)

        checks.append(
            {
                "name": label,
                "rule": rule_id,
                "status": status,
                "detected_value": (
                    rule_result.get("detected_value")
                    if rule_result
                    else None
                ),
                "reason": (
                    rule_result.get("reason")
                    if rule_result
                    else "Requirement not assessed."
                ),
            }
        )

    # N/A declarations (for example country of origin on a domestic package)
    # are excluded from the denominator rather than being shown as missing.
    applicable_mandatory = [c for c in checks if c["status"] != "N/A"]
    mandatory_present = sum(1 for c in applicable_mandatory if c["status"] == "PASS")
    mandatory_total = len(applicable_mandatory)

    declaration_score = _declaration_score(rule_checks)

    # --------------------------------------------------------
    # OVERALL SCORE
    # --------------------------------------------------------

    overall_score = round(
        declaration_score * 0.70
        + visual_score * 0.30
    )

    declaration_applicable = [
        r for r in rule_checks
        if r.get("rule") in {
            "Rule 6(1)(a)", "Rule 6(1)(aa)", "Rule 6(1)(b)",
            "Rule 6(1)(c)", "Rule 6(1)(d)", "Rule 6(1)(e)", "Rule 6(1)(f)"
        } and r.get("status") != "N/A"
    ]
    declaration_coverage = round(
        100 * sum(1 for r in declaration_applicable if r.get("status") in {"PASS", "FAIL"})
        / len(declaration_applicable)
    ) if declaration_applicable else 0

    # --------------------------------------------------------
    # WARNINGS
    # --------------------------------------------------------

    warnings = []
    warning_messages = []

    for rule in rule_checks:

        if rule.get("status") == "REVIEW_REQUIRED":

            warning = (
                f"{rule.get('rule')}: "
                f"{rule.get('reason')}"
            )

            warnings.append(warning)
            warning_messages.append(warning)

    # Product-date alert is deliberately separate from Rule 6 presence.
    # A past use-by date is a useful inspection finding, but is not silently
    # converted into a Legal Metrology declaration failure.
    expiry_text = str(vlm_result.get("expiry_or_best_before") or "")
    expiry_match = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b", expiry_text)
    if expiry_match:
        try:
            from datetime import datetime as _dt
            expiry_dt = _dt.strptime(
                f"{expiry_match.group(1)} {expiry_match.group(2)[:3]} {expiry_match.group(3)}",
                "%d %b %Y",
            )
            if expiry_dt.date() < _dt.now().date():
                date_warning = f"PRODUCT DATE ALERT: Use-by/best-before date appears to have passed ({expiry_text})."
                warnings.append(date_warning)
                warning_messages.append(date_warning)
        except ValueError:
            pass

    # Visual warnings
    visual = vlm_result.get("visual_analysis") or {}

    if visual.get("visual_warnings"):

        for warning in visual.get("visual_warnings"):
            warning_messages.append(str(warning))

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    hard_fail = any(
        r.get("status") == "FAIL"
        for r in rule_checks
        if r.get("rule") in {
            "Rule 6(1)(a)",
            "Rule 6(1)(aa)",
            "Rule 6(1)(b)",
            "Rule 6(1)(c)",
            "Rule 6(1)(d)",
            "Rule 6(1)(e)",
            "Rule 6(1)(f)",
        }
    )

    visual_fail = any(
        v.get("status") == "FAIL"
        for v in visual_checks
    )

    visual_review = any(
        v.get("status") == "REVIEW_REQUIRED"
        for v in visual_checks
    )

    if hard_fail:
        status = "NON_COMPLIANT"

    elif visual_fail:
        status = "REQUIRES_RESCAN"

    elif warnings or visual_review:
        status = "COMPLIANT_WITH_WARNINGS"

    else:
        status = "COMPLIANT"

    # --------------------------------------------------------
    # ADDITIONAL INFORMATION
    # --------------------------------------------------------

    additional_information = {
        "rules_version": RULES_VERSION,
        "ocr_used": False,
        "decision_source": "Gemini VLM + Visual Compliance Analysis",
        "physical_verification_required": True,
        "contextual_verification_required": True,
        "rule_count_evaluated": len(rule_checks),
        "rule_registry_total": len(RULE_REGISTRY),
        "rule_registry_version": RULES_VERSION,
        "classification": evaluate_applicability(vlm_result).get("classification", {}),
        "applicability_engine": "scope-and-context-v1",
    }

    return {
        "status": status,
        "score": overall_score,
        "declaration_score": declaration_score,
        "visual_score": visual_score,
        "declaration_coverage": declaration_coverage,

        "mandatory_present": mandatory_present,
        "mandatory_missing": mandatory_missing,
        "mandatory_total": mandatory_total,
        "mandatory_applicable": mandatory_total,

        "warnings": warnings,
        "warning_messages": warning_messages,

        "ocr_confidence": 0,
        "raw_text": "",

        "vlm": vlm_result,
        "vlm_error": None,

        "checks": checks,
        "rule_checks": rule_checks,

        "visual_checks": visual_checks,

        "visual_assessment": {
            "overall_status": (
                "FAIL"
                if visual_fail
                else (
                    "REVIEW_REQUIRED"
                    if visual_review
                    else "PASS"
                )
            ),
            "image_quality": visual.get(
                "image_quality",
                "UNKNOWN"
            ),
            "overall_readability": visual.get(
                "overall_readability",
                "UNKNOWN"
            ),
            "declaration_placement": visual.get(
                "declaration_placement",
                "UNKNOWN"
            ),
        },

        "additional_information": additional_information,

        "evidence": vlm_result.get(
            "evidence",
            []
        ),

        "timestamp": timestamp,
    }