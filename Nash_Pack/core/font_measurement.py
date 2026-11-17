"""Physical lettering measurement using VLM localization + calibrated CV.

Gemini remains the perception/localization layer.  Computer vision measures
actual glyph components inside the VLM ROI instead of treating the whole VLM
bounding box as the font height.
"""
from typing import Any, Dict, Iterable, Optional, Tuple
import cv2
import numpy as np

from core.measurement_quality import assess_image_quality
from core.glyph_measurement import measure_glyph_height

# Only declaration fields that correspond to Rule 6 declaration checks are
# measured. Decorative/brand/FSSAI/batch text is intentionally excluded.
FONT_FIELDS = {
    "mrp", "net_quantity", "common_name", "product_name", "manufacturer_name",
    "manufacturer_address", "importer_name", "importer_address", "consumer_care", "country_of_origin", "manufacturing_date", "expiry_or_best_before",
    "unit_sale_price",
}

# product_name is only a fallback for the Rule 6(1)(b) common/generic-name
# declaration. It must never appear as a second independent font result when
# common_name is already present.
FONT_CANONICAL = {
    "product_name": "common_name",
    "common_name": "common_name",
    "manufacturer_name": "manufacturer",
    "manufacturer_address": "manufacturer",
    "importer_name": "manufacturer",
    "importer_address": "manufacturer",
    "manufacturing_date": "manufacturing_date",
    "expiry_or_best_before": "best_before",
    "unit_sale_price": "unit_sale_price",
}

RULE7_TABLE_NORMAL = [(50.0, 1.0), (100.0, 1.5), (500.0, 2.5), (2500.0, 4.0), (float("inf"), 6.0)]
RULE7_TABLE_FORMED = [(50.0, 2.0), (100.0, 3.0), (500.0, 4.0), (2500.0, 6.0), (float("inf"), 6.0)]


def filter_applicable_font_regions(vlm, evidence_regions):
    """Filter VLM evidence to declarations that are applicable Rule 7 targets.

    Gemini extraction is untouched. This downstream gate prevents brand, slogan,
    FSSAI, barcode, batch and other non-Rule-6 text from entering physical font
    measurement. Conditional importer/origin and unit-sale-price fields are also
    gated by package context.
    """
    vlm = vlm or {}
    regions = evidence_regions or []
    imported = bool(vlm.get("is_imported") or vlm.get("importer_name") or vlm.get("importer_address"))
    common_present = bool(vlm.get("common_name"))
    wholesale = bool(vlm.get("wholesale_package"))
    combo_or_multi = bool(vlm.get("combination_or_multi_piece_package"))

    allowed = {
        "mrp", "net_quantity", "common_name", "product_name",
        "manufacturer_name", "manufacturer_address", "consumer_care",
        "manufacturing_date", "expiry_or_best_before",
    }
    if imported:
        allowed.update({"importer_name", "importer_address", "country_of_origin"})
    if not wholesale and not combo_or_multi:
        allowed.add("unit_sale_price")

    out = []
    for region in regions:
        field = str(region.get("field") or "").strip().lower()
        if field not in allowed:
            continue
        # product_name is a fallback for the common/generic-name declaration,
        # never a second measurement when common_name has already been found.
        if field == "product_name" and common_present:
            continue
        out.append(region)

    seen = set()
    unique = []
    for region in out:
        key = (str(region.get("field") or ""), tuple(region.get("bbox") or []), str(region.get("text") or ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(region)
    return unique


def _valid_bbox(bbox: Any) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return False
    try:
        ymin, xmin, ymax, xmax = [float(x) for x in bbox]
    except (TypeError, ValueError):
        return False
    return 0 <= ymin < ymax <= 1000 and 0 <= xmin < xmax <= 1000


def _px_bbox(norm_bbox, width, height):
    """evidence_regions boxes are [ymin, xmin, ymax, xmax] (Gemini's standard order)."""
    ymin, xmin, ymax, xmax = [float(v) for v in norm_bbox]
    return [max(0, min(width - 1, int(round(xmin * width / 1000)))),
            max(0, min(height - 1, int(round(ymin * height / 1000)))),
            max(0, min(width - 1, int(round(xmax * width / 1000)))),
            max(0, min(height - 1, int(round(ymax * height / 1000))))]


def _px_bbox_xyxy(norm_bbox, width, height):
    """principal_display_panel_bbox is [x1, y1, x2, y2] — a DIFFERENT order than
    evidence_regions boxes. Mixing these up silently corrupts the estimated PDP
    area (and therefore the Rule 7 minimum lettering height selected), so this
    is kept as an explicitly separate helper instead of reusing _px_bbox."""
    x1, y1, x2, y2 = [float(v) for v in norm_bbox]
    return [max(0, min(width - 1, int(round(x1 * width / 1000)))),
            max(0, min(height - 1, int(round(y1 * height / 1000)))),
            max(0, min(width - 1, int(round(x2 * width / 1000)))),
            max(0, min(height - 1, int(round(y2 * height / 1000))))]


def _transform_points(points, H):
    pts = np.asarray(points, dtype=np.float32).reshape(-1, 1, 2)
    out = cv2.perspectiveTransform(pts, np.asarray(H, dtype=np.float64)).reshape(-1, 2)
    return out


def _rectified_roi(image, bbox_px, calibration) -> Tuple[np.ndarray, Dict[str, Any]]:
    H = calibration.get("homography") if calibration else None
    x1, y1, x2, y2 = bbox_px
    if not H:
        return image[y1:y2, x1:x2], {"bbox_rectified": bbox_px, "perspective_corrected": False}

    H = np.asarray(H, dtype=np.float64)
    # Transform the complete source image footprint so the homography can be
    # translated into a positive output canvas. This preserves the marker-derived
    # scale while allowing text anywhere on the same package plane.
    ih, iw = image.shape[:2]
    footprint = _transform_points([[0,0],[iw-1,0],[iw-1,ih-1],[0,ih-1]], H)
    min_xy = np.floor(footprint.min(axis=0)).astype(int)
    max_xy = np.ceil(footprint.max(axis=0)).astype(int)
    tx, ty = -min(0, int(min_xy[0])), -min(0, int(min_xy[1]))
    T = np.array([[1,0,tx],[0,1,ty],[0,0,1]], dtype=np.float64)
    M = T @ H
    out_w = max(2, int(max_xy[0] + tx + 2))
    out_h = max(2, int(max_xy[1] + ty + 2))
    warped = cv2.warpPerspective(image, M, (out_w, out_h))
    corners = _transform_points([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], M)
    rx1, ry1 = np.floor(corners.min(axis=0)).astype(int)
    rx2, ry2 = np.ceil(corners.max(axis=0)).astype(int)
    rx1, ry1 = max(0, rx1), max(0, ry1)
    rx2, ry2 = min(out_w, rx2), min(out_h, ry2)
    if rx2 <= rx1 or ry2 <= ry1:
        return np.empty((0,0,3), dtype=np.uint8), {"bbox_rectified": None, "perspective_corrected": True}
    return warped[ry1:ry2, rx1:rx2], {"bbox_rectified": [int(rx1),int(ry1),int(rx2),int(ry2)], "perspective_corrected": True}


def _estimate_text_height_px(image, bbox_px) -> Tuple[Optional[float], Dict[str, Any]]:
    x1, y1, x2, y2 = bbox_px
    if x2 <= x1 or y2 <= y1:
        return None, {}
    roi = image[y1:y2, x1:x2]
    if roi.size == 0:
        return None, {}
    return measure_glyph_height(roi, upscale_factor=4)


def _rule7_threshold(area_cm2: float, formed=False) -> float:
    for upper, minimum in RULE7_TABLE_FORMED if formed else RULE7_TABLE_NORMAL:
        if area_cm2 <= upper: return minimum
    return 6.0


def rule7_minimum_for_area(area_cm2: float, formed: bool = False) -> float:
    """Public wrapper so standalone/marker-free tools (e.g. the AR ruler, which
    never runs the full VLM+image pipeline) can reuse the exact same statutory
    table used by the photo-based measurement path."""
    return _rule7_threshold(float(area_cm2), formed=formed)


def _estimate_pdp(image_shape, calibration, pdp_bbox):
    if not calibration.get("available") or not _valid_bbox(pdp_bbox): return None
    h, w = image_shape[:2]
    x1, y1, x2, y2 = _px_bbox_xyxy(pdp_bbox, w, h)
    H = calibration.get("homography")
    if H:
        pts = _transform_points([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], H)
        pw = max(1.0, float(pts[:,0].max()-pts[:,0].min()))
        ph = max(1.0, float(pts[:,1].max()-pts[:,1].min()))
        ppm = float(calibration.get("rectified_pixels_per_mm") or 1.0)
        width_mm, height_mm = pw/ppm, ph/ppm
    else:
        mmpp = float(calibration["mm_per_pixel"])
        width_mm, height_mm = (x2-x1)*mmpp, (y2-y1)*mmpp
    return {"bbox_pixels":[x1,y1,x2,y2], "width_mm":round(width_mm,2), "height_mm":round(height_mm,2), "area_cm2":round(width_mm*height_mm/100,2)}


def measure_font_sizes(image_path: str, evidence_regions: Iterable[Dict[str, Any]], calibration: Dict[str, Any], pdp_bbox=None, formed=False, medical_device=False, scale_source=None) -> Dict[str, Any]:
    image = cv2.imread(image_path)
    if image is None: return {"status":"ERROR","items":[],"reason":"Image could not be loaded."}
    quality = assess_image_quality(image)
    height, width = image.shape[:2]
    # scale_source may be a QR-reference package-dimension or AR world calibration.
    if scale_source and scale_source.get("available"):
        calibration = dict(calibration or {})
        calibration.update(scale_source)
    calibrated = bool(calibration.get("available"))
    pdp = _estimate_pdp(image.shape, calibration, pdp_bbox)
    threshold = None if medical_device or not pdp else _rule7_threshold(pdp["area_cm2"], formed)
    items = []
    for region in evidence_regions or []:
        field = str(region.get("field") or "").strip().lower()
        if field not in FONT_FIELDS or not _valid_bbox(region.get("bbox")): continue
        bbox_px = _px_bbox(region["bbox"], width, height)
        roi, rect_info = _rectified_roi(image, bbox_px, calibration)
        if roi.size == 0: continue
        measured_px, glyph_info = _estimate_text_height_px(roi, [0,0,roi.shape[1],roi.shape[0]])
        if measured_px is None: continue
        item = {
            "field":field, "text":region.get("text"), "bbox":list(region["bbox"]), "bbox_pixels":bbox_px,
            "vlm_confidence":region.get("confidence"), "measurement_method":"Gemini VLM localization + high-resolution CV glyph measurement",
            "lettering_height_px":round(measured_px,2), "physical_scale_available": calibrated, "quality":quality, **rect_info, **glyph_info,
        }
        if calibrated:
            ppm = float(calibration.get("rectified_pixels_per_mm") or 0)
            mm = measured_px / ppm if ppm else measured_px * float(calibration["mm_per_pixel"])
            item["lettering_height_mm"] = round(mm,3)
            spread_px = float(item.get("glyph_height_spread_px") or 0.0)
            item["estimated_measurement_uncertainty_mm"] = round(max(0.05, spread_px / ppm) if ppm else 0.0, 3)
            item["measurement_confidence"] = item.get("measurement_confidence", "MEDIUM")

            # Preserve each detected glyph height so the UI can expose the
            # underlying measurement on demand. The final declaration height
            # remains a robust median rather than a naive arithmetic average.
            glyph_boxes = item.get("glyph_boxes") or []
            glyph_details = []
            for gi, gb in enumerate(glyph_boxes, 1):
                try:
                    gh_px = max(0.0, float(gb[3]) - float(gb[1]))
                    gh_mm = gh_px / ppm if ppm else gh_px * float(calibration["mm_per_pixel"])
                    glyph_details.append({
                        "index": gi,
                        "height_px": round(gh_px, 2),
                        "height_mm": round(gh_mm, 3),
                        "bbox": gb,
                    })
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
            item["glyph_details"] = glyph_details
            item["final_height_method"] = "Robust median of accepted glyph heights"
            if threshold is not None:
                item["rule7_minimum_mm"] = threshold
                item["rule7_status"] = "PASS" if quality["sharp_enough"] and mm + 0.10 >= threshold else ("REVIEW_REQUIRED" if not quality["sharp_enough"] else "FAIL")
                item["rule7_reason"] = f"Estimated glyph height {mm:.3f} mm vs Rule 7 minimum {threshold:.1f} mm for estimated PDP area {pdp['area_cm2']:.2f} cm²."
            else:
                item["rule7_status"] = "REVIEW_REQUIRED"
                item["rule7_reason"] = "Physical height was calibrated, but no statutory threshold was assigned because PDP area or a special category could not be established."
            item["status"] = "MEASURED" if quality["sharp_enough"] else "REVIEW_REQUIRED"
            item["reason"] = "Physical scale + package-plane perspective correction used." if quality["sharp_enough"] else "Calibration exists, but the captured image is too blurry for a defensible glyph-height measurement."
        else:
            item.update({"lettering_height_mm":None,"status":"REVIEW_REQUIRED","rule7_status":"REVIEW_REQUIRED","reason":"Lettering was localized by Gemini and glyphs were measured in pixels, but no defensible physical millimetre scale is available.","physical_scale_available":False})
        items.append(item)
    measured = bool(calibrated and items and any(i.get("status") == "MEASURED" for i in items))
    return {
        "status":"MEASURED" if measured else "REVIEW_REQUIRED", "calibration_available":calibrated, "physical_unit":"mm" if calibrated else None,
        "image_quality":quality, "pdp_measurement":pdp, "rule7_minimum_mm":threshold,
        "items":items,
        "reason":"Calibrated glyph-height measurements were generated from Gemini-localized regions." if measured else "No defensible calibrated glyph-height measurement was available.",
    }
