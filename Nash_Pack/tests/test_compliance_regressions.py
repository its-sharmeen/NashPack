import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.compliance_engine import run_compliance_check
from core.presentation_engine import evaluate_presentation
from core.declaration_engine import validate_declarations
from core.applicability_engine import classify_package


def package(imported=False, country="India"):
    return {
        "product_name": "Salted Peanuts",
        "common_name": "Salted Peanuts",
        "manufacturer_name": "HALDIRAM SNACKS PVT. LTD.",
        "manufacturer_address": "H01/H05 Noida",
        "importer_name": None,
        "importer_address": None,
        "net_quantity": "200g",
        "mrp": "₹44.00",
        "mrp_inclusive_of_taxes": True,
        "manufacturing_date": "26.05.16",
        "expiry_or_best_before": "25.10.16",
        "consumer_care": {"phone": "1800-180-0501", "email": "care@example.com"},
        "country_of_origin": country,
        "is_imported": imported,
        "unit_sale_price": None,
        "wholesale_package": False,
        "combination_or_multi_piece_package": False,
        "evidence": [],
        "visual_analysis": {
            "mandatory_text_readability": "CLEAR",
            "declaration_placement": "CLEAR",
            "possible_font_size_issue": False,
        },
    }


class ComplianceRegressionTests(unittest.TestCase):
    def test_domestic_country_does_not_trigger_imported_logic(self):
        checks = validate_declarations(package(False))
        country = next(x for x in checks["checks"] if x["rule"] == "Rule 6(1)(aa)")
        self.assertEqual(country["status"], "N/A")

    def test_date_with_day_month_year_is_accepted_for_month_year_declaration(self):
        checks = validate_declarations(package(False))
        mfg = next(x for x in checks["checks"] if x["rule"] == "Rule 6(1)(d)")
        self.assertEqual(mfg["status"], "PASS")

    def test_compact_quantity_units_are_recognized(self):
        rows = evaluate_presentation({"net_quantity": "200g", "visual_analysis": {}})
        self.assertEqual(next(x for x in rows if x["rule"] == "Rule 11")["status"], "PASS")
        self.assertEqual(next(x for x in rows if x["rule"] == "Rule 13")["status"], "PASS")

    def test_no_exemption_is_not_a_rule_26_failure(self):
        result = run_compliance_check(package(False))
        rule26 = next(x for x in result["rule_checks"] if x["rule"] == "Rule 26")
        self.assertEqual(rule26["status"], "NOT_APPLICABLE")

    def test_imported_without_country_fails_country_rule(self):
        result = run_compliance_check(package(True, None))
        country = next(x for x in result["rule_checks"] if x["rule"] == "Rule 6(1)(aa)")
        self.assertEqual(country["status"], "FAIL")
        self.assertEqual(result["status"], "NON_COMPLIANT")

    def test_mrp_tax_inclusive_phrase_in_vlm_evidence_confirms_mrp(self):
        data = package(False)
        data["mrp_inclusive_of_taxes"] = False
        data["evidence"] = ["MRP ₹44.00", "FOR MRP ₹ (INCL. OF ALL TAXES)"]
        checks = validate_declarations(data)
        mrp = next(x for x in checks["checks"] if x["rule"] == "Rule 6(1)(e)")
        self.assertEqual(mrp["status"], "PASS")

    def test_na_country_is_excluded_from_mandatory_count(self):
        result = run_compliance_check(package(False))
        self.assertEqual(result["mandatory_present"], 6)
        self.assertEqual(result["mandatory_total"], 6)

    def test_food_category_uses_vlm_category_and_fssai_fallback(self):
        data = package(False)
        data["product_category"] = "FOOD"
        data["product_category_confidence"] = 0.96
        self.assertTrue(classify_package(data)["food"])

        legacy = package(False)
        legacy["product_category"] = "UNKNOWN"
        legacy["fssai_numbers"] = ["12345678901234"]
        self.assertTrue(classify_package(legacy)["food"])

    def test_annotation_dedupe_is_semantic_not_only_near_exact_iou(self):
        from core.annotation_engine import _dedupe_regions
        regions = [
            {"field":"product_name","text":"Desi Ghee","bbox":[300,300,600,650],"confidence":0.9},
            {"field":"common_name","text":"Desi Ghee","bbox":[315,320,560,500],"confidence":0.95},
        ]
        out = _dedupe_regions(regions)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bbox"], [315.0,320.0,560.0,500.0])


    def test_annotation_dedupe_removes_nested_product_common_boxes(self):
        from core.annotation_engine import _dedupe_regions
        # Product title encloses the common-name word "PEANUTS". The boxes have
        # low IoU because the inner box is much smaller, but the inner box is
        # almost completely contained in the outer one.
        regions = [
            {"field":"product_name","text":"CLASSIC salted PEANUTS","bbox":[55,535,245,810],"confidence":0.95},
            {"field":"common_name","text":"PEANUTS","bbox":[175,545,238,805],"confidence":0.94},
        ]
        out = _dedupe_regions(regions)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["bbox"], [175.0,545.0,238.0,805.0])

    def test_gemini_bbox_uses_ymin_xmin_ymax_xmax_order(self):
        from core.annotation_engine import _bbox_to_px
        # 1000x1000 image: Gemini [ymin, xmin, ymax, xmax]
        self.assertEqual(
            _bbox_to_px([100, 200, 300, 400], 1000, 1000),
            (200, 100, 400, 300),
        )

    def test_past_use_by_is_warning_not_declaration_failure(self):
        data = package(False)
        data["expiry_or_best_before"] = "01 MAY 2025"
        result = run_compliance_check(data)
        self.assertTrue(any("PRODUCT DATE ALERT" in x for x in result["warning_messages"]))
        expiry_rule = next(x for x in result["rule_checks"] if x["rule"] == "Rule 6(1)(da)")
        self.assertEqual(expiry_rule["status"], "PASS")


if __name__ == "__main__":
    unittest.main()


def test_annotation_renderer_writes_output(tmp_path):
    import cv2
    import numpy as np
    from core.annotation_engine import annotate_image

    src = tmp_path / "src.jpg"
    out = tmp_path / "annotated" / "out.jpg"
    cv2.imwrite(str(src), np.full((120, 180, 3), 240, dtype=np.uint8))
    result = annotate_image(
        str(src), str(out),
        [{"field": "common_name", "text": "PEANUTS", "bbox": [100, 200, 300, 700]}]
    )
    assert out.exists()
    assert result["regions_annotated"] == 1


def test_annotation_focuses_on_legal_metrology_and_expands_plain_space(tmp_path):
    import cv2
    import numpy as np
    from core.annotation_engine import annotate_image

    src = tmp_path / "package.jpg"
    out = tmp_path / "annotated.jpg"
    img = np.full((500, 700, 3), 240, dtype=np.uint8)
    cv2.rectangle(img, (80, 50), (620, 450), (180, 180, 180), -1)
    cv2.imwrite(str(src), img)

    regions = [
        {"field": "brand_name", "text": "Haldiram's", "bbox": [100, 100, 160, 300]},
        {"field": "common_name", "text": "salted peanuts", "bbox": [180, 550, 250, 680]},
        {"field": "net_quantity", "text": "200g", "bbox": [280, 560, 315, 630]},
        {"field": "mrp", "text": "Rs. 44.00", "bbox": [320, 550, 350, 640]},
        {"field": "batch_number", "text": "HC511C", "bbox": [360, 550, 390, 640]},
        {"field": "fssai_number", "text": "10012051000107", "bbox": [400, 550, 430, 680]},
        {"field": "consumer_care", "text": "0120-2400286", "bbox": [300, 100, 335, 300]},
    ]
    result = annotate_image(str(src), str(out), regions)
    assert result["regions_annotated"] == 4
    assert result["annotation_scope"] == "legal_metrology_declarations_only"
    annotated = cv2.imread(str(out))
    assert annotated is not None
    assert annotated.shape[1] > img.shape[1]


def test_presentation_uses_one_font_result_per_applicable_declaration():
    from core.presentation_engine import build_result_view_model

    result = package(False)
    result.update({
        "status": "COMPLIANT_WITH_WARNINGS",
        "score": 100,
        "warning_messages": [],
        "visual_assessment": {"overall_readability": "CLEAR", "declaration_placement": "CLEAR"},
        "rule_checks": [
            {"rule":"Rule 6(1)(a)","status":"PASS","detected_value":"Maker","reason":"ok","applicability":"APPLICABLE"},
            {"rule":"Rule 6(1)(aa)","status":"N/A","detected_value":None,"reason":"domestic","applicability":"NOT_APPLICABLE"},
            {"rule":"Rule 6(1)(b)","status":"PASS","detected_value":"Salted Peanuts","reason":"ok","applicability":"APPLICABLE"},
            {"rule":"Rule 6(1)(c)","status":"PASS","detected_value":"200 g","reason":"ok","applicability":"APPLICABLE"},
        ],
        "font_measurement": {"items": [
            {"field":"common_name","lettering_height_mm":2.0,"rule7_minimum_mm":1.0,"rule7_status":"PASS","image_index":1,"glyph_details":[]},
            {"field":"common_name","lettering_height_mm":2.2,"rule7_minimum_mm":1.0,"rule7_status":"PASS","image_index":2,"glyph_details":[]},
        ]},
        "images": [],
    })
    vm = build_result_view_model(result, {"id":1,"product_label":"Salted Peanuts"})
    common = [x for x in vm["declarations"] if x["rule"] == "Rule 6(1)(b)"][0]
    assert common["font"]["height_mm"] == 2.1
    assert common["font"]["minimum_mm"] == 1.0
    assert common["font"]["rule7_status"] == "PASS"
    assert "readability" not in common
    assert "placement" not in common
    assert vm["visual_summary"]["readability"] == "CLEAR"


def test_font_region_filter_excludes_irrelevant_and_non_applicable_text():
    from core.font_measurement import filter_applicable_font_regions
    vlm = {
        "common_name": "Salted Peanuts",
        "is_imported": False,
        "wholesale_package": False,
        "combination_or_multi_piece_package": False,
    }
    regions = [
        {"field":"brand_name","bbox":[1,1,10,10],"text":"Brand"},
        {"field":"common_name","bbox":[20,20,30,40],"text":"Salted Peanuts"},
        {"field":"product_name","bbox":[40,20,50,40],"text":"Salted Peanuts"},
        {"field":"fssai_number","bbox":[50,20,60,40],"text":"12345678901234"},
        {"field":"country_of_origin","bbox":[60,20,70,40],"text":"INDIA"},
        {"field":"importer_name","bbox":[70,20,80,40],"text":"Importer"},
        {"field":"unit_sale_price","bbox":[80,20,90,40],"text":"₹220/kg"},
    ]
    out = filter_applicable_font_regions(vlm, regions)
    fields = [x["field"] for x in out]
    assert fields == ["common_name", "unit_sale_price"]


def test_font_region_filter_allows_product_name_only_when_common_name_missing():
    from core.font_measurement import filter_applicable_font_regions
    vlm = {"common_name": None, "is_imported": False}
    regions = [{"field":"product_name","bbox":[20,20,30,40],"text":"Salted Peanuts"}]
    assert [x["field"] for x in filter_applicable_font_regions(vlm, regions)] == ["product_name"]
