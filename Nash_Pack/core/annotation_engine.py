"""SIH26034 Legal Metrology evidence annotation renderer.

Design goal: mark only declarations relevant to Packaged Commodities compliance on
 the package itself, and put the explanatory text in clean white side margins.
"""

import os
import re
from typing import Any, Dict, Iterable

import cv2


def _bbox_to_px(bbox, width, height):
    """Gemini normalized boxes are [ymin, xmin, ymax, xmax] in 0..1000."""
    ymin, xmin, ymax, xmax = [float(v) for v in bbox]
    return (
        max(0, min(width - 1, int(round(xmin * width / 1000.0)))),
        max(0, min(height - 1, int(round(ymin * height / 1000.0)))),
        max(0, min(width - 1, int(round(xmax * width / 1000.0)))),
        max(0, min(height - 1, int(round(ymax * height / 1000.0)))),
    )


def _norm_text(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _bbox_iou(a, b):
    try:
        ax1, ay1, ax2, ay2 = map(float, a)
        bx1, by1, bx2, by2 = map(float, b)
    except Exception:
        return 0.0
    ix1, iy1, ix2, iy2 = max(ax1, bx1), max(ay1, by1), min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    aa = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    bb = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / max(1e-9, aa + bb - inter)


def _area(bbox):
    try:
        x1, y1, x2, y2 = map(float, bbox)
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)
    except Exception:
        return 0.0


def _intersection_over_smaller(a, b):
    try:
        ax1, ay1, ax2, ay2 = map(float, a)
        bx1, by1, bx2, by2 = map(float, b)
    except Exception:
        return 0.0
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    return ((ix2 - ix1) * (iy2 - iy1)) / max(1e-9, min(_area(a), _area(b)))


def _same_semantics(a, b):
    af = str(a.get("field") or "evidence").strip().lower()
    bf = str(b.get("field") or "evidence").strip().lower()
    at = _norm_text(a.get("text"))
    bt = _norm_text(b.get("text"))
    if af == bf:
        return True
    if at and bt and (at == bt or at in bt or bt in at):
        return True
    if {af, bf} <= {"product_name", "common_name"}:
        return True
    return False


def _merge_regions(winner, loser):
    winner = dict(winner)
    labels = []
    for source in (winner, loser):
        for key in ("field", "label"):
            value = str(source.get(key) or "").strip()
            if value and value.lower() not in {x.lower() for x in labels}:
                labels.append(value)
    texts = []
    for source in (winner, loser):
        value = str(source.get("text") or "").strip()
        if value and _norm_text(value) not in {_norm_text(x) for x in texts}:
            texts.append(value)
    winner["annotation_labels"] = labels
    if texts:
        winner["text"] = " / ".join(texts)[:90]
    winner["confidence"] = max(float(winner.get("confidence") or 0), float(loser.get("confidence") or 0))
    return winner


def _dedupe_regions(regions):
    candidates = []
    for r in regions or []:
        bbox = r.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            vals = list(map(float, bbox))
            if vals[2] <= vals[0] or vals[3] <= vals[1]:
                continue
        except Exception:
            continue
        rr = dict(r)
        rr["bbox"] = vals
        candidates.append(rr)

    candidates.sort(key=lambda r: _area(r["bbox"]))
    kept = []
    for region in candidates:
        replaced = False
        for i, existing in enumerate(kept):
            iou = _bbox_iou(region["bbox"], existing["bbox"])
            ios = _intersection_over_smaller(region["bbox"], existing["bbox"])
            same = _same_semantics(region, existing)
            if same:
                if ios < 0.45:
                    continue
            else:
                if iou < 0.75 and ios < 0.92:
                    continue
            winner = region if _area(region["bbox"]) < _area(existing["bbox"]) else existing
            loser = existing if winner is region else region
            kept[i] = _merge_regions(winner, loser)
            replaced = True
            break
        if not replaced:
            kept.append(region)
    return kept


# Only these are relevant to the Packaged Commodities declaration/compliance view.
# Deliberately excluded: brand, batch number, FSSAI, ingredients, nutrition, barcode,
# logos/certifications, marketing text, etc. They may be useful evidence but are not
# part of the focused Legal Metrology annotation layer.
_LEGAL_FIELDS = {
    "common_name",
    "net_quantity",
    "mrp",
    "maximum_retail_price",
    "manufacturer_name",
    "manufacturer_address",
    "packer_name",
    "packer_address",
    "importer_name",
    "importer_address",
    "country_of_origin",
    "manufacturing_date",
    "packing_date",
    "best_before",
    "best_before_date",
    "use_by",
    "use_by_date",
    "expiry",
    "expiry_date",
    "consumer_care",
    "consumer_care_address",
    "consumer_care_phone",
    "consumer_care_email",
    "unit_sale_price",
    "dimensions",
}


def _field_name(region):
    return str(region.get("field") or "").strip().lower().replace(" ", "_")


def _is_legal_field(region):
    field = _field_name(region)
    if field in _LEGAL_FIELDS:
        return True
    # tolerate naming variants emitted by different prompt/model versions
    return any(token in field for token in (
        "common_name", "net_quantity", "maximum_retail", "mrp",
        "manufacturer", "packer", "importer", "country_of_origin",
        "manufacturing_date", "packing_date", "best_before", "use_by",
        "expiry", "consumer_care", "unit_sale_price", "dimensions",
    ))


def _filter_legal_regions(regions):
    """Select only useful Legal Metrology declarations for visual annotation."""
    out = []
    seen = set()
    for r in regions:
        if not _is_legal_field(r):
            continue
        field = _field_name(r)
        # Never show product_name separately: common/generic name is the legal focus.
        if field == "product_name":
            continue
        key = (field, _norm_text(r.get("text")))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _wrap_text(text, max_chars=28):
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        candidate = word if not current else current + " " + word
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _label_content(region):
    field = _field_name(region)
    names = {
        "common_name": "Common / generic name",
        "net_quantity": "Net quantity",
        "mrp": "MRP (incl. all taxes)",
        "maximum_retail_price": "MRP (incl. all taxes)",
        "manufacturer_name": "Manufacturer / packer",
        "manufacturer_address": "Manufacturer address",
        "packer_name": "Packer",
        "packer_address": "Packer address",
        "importer_name": "Importer",
        "importer_address": "Importer address",
        "country_of_origin": "Country of origin",
        "manufacturing_date": "Mfg. date",
        "packing_date": "Packing date",
        "best_before": "Best before",
        "best_before_date": "Best before",
        "use_by": "Use-by date",
        "use_by_date": "Use-by date",
        "expiry": "Expiry date",
        "expiry_date": "Expiry date",
        "consumer_care": "Consumer care",
        "consumer_care_address": "Consumer care",
        "consumer_care_phone": "Consumer care",
        "consumer_care_email": "Consumer care",
        "unit_sale_price": "Unit sale price",
        "dimensions": "Dimensions",
    }
    title = names.get(field, field.replace("_", " ").title())
    value = str(region.get("text") or "").strip()
    return title, value


def _draw_callout(canvas, packet_x, packet_y, box, side, label_y, title, value, color, gutter, font_scale):
    """Draw a leader line from the marked packet region to a clean side label."""
    h, w = canvas.shape[:2]
    x1, y1, x2, y2 = box
    pad = 7
    max_text = 30
    lines = [title]
    if value:
        lines += _wrap_text(value[:80], max_text)[:2]
    fs = font_scale
    thickness = 1
    sizes = [cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, fs, thickness)[0] for line in lines]
    tw = max(s[0] for s in sizes)
    line_h = max(17, int(20 * fs / 0.48))
    lh = pad * 2 + line_h * len(lines)
    lw = min(gutter - 24, max(170, tw + pad * 2))
    label_y = int(max(8, min(h - lh - 8, label_y)))

    if side == "left":
        lx = 12
        target_x = lx + lw
        anchor = (packet_x + x1, packet_y + (y1 + y2) // 2)
        elbow = (packet_x - 12, int(label_y + lh / 2))
        end = (target_x, int(label_y + lh / 2))
    else:
        lx = w - gutter + 12
        target_x = lx
        anchor = (packet_x + x2, packet_y + (y1 + y2) // 2)
        elbow = (packet_x + int(canvas.shape[1] - 2 * gutter) + 12, int(label_y + lh / 2))
        # Simpler and robust: route through the packet's right edge into the right gutter.
        elbow = (packet_x + (w - 2 * gutter) + 12, int(label_y + lh / 2))
        end = (lx, int(label_y + lh / 2))

    # leader line stays outside the packet except for the short connection to the box
    cv2.line(canvas, anchor, elbow, color, 2, cv2.LINE_AA)
    cv2.line(canvas, elbow, end, color, 2, cv2.LINE_AA)
    cv2.circle(canvas, anchor, 4, color, -1, cv2.LINE_AA)

    cv2.rectangle(canvas, (lx, label_y), (lx + lw, label_y + lh), (255, 255, 255), -1)
    cv2.rectangle(canvas, (lx, label_y), (lx + lw, label_y + lh), color, 2)
    yy = label_y + pad + line_h - 4
    for i, line in enumerate(lines):
        weight = 2 if i == 0 else 1
        cv2.putText(canvas, line, (lx + pad, yy), cv2.FONT_HERSHEY_SIMPLEX, fs, color, weight, cv2.LINE_AA)
        yy += line_h


def annotate_image(image_path: str, output_path: str, evidence_regions: Iterable[Dict[str, Any]], calibration: Dict[str, Any] | None = None, pdp_bbox=None) -> Dict[str, Any]:
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError("Unable to load image for annotation")

    h, w = image.shape[:2]
    all_regions = _dedupe_regions(evidence_regions)
    regions = _filter_legal_regions(all_regions)

    # Expand the canvas. The package remains at its original resolution in the
    # centre; all explanatory text lives in clean white side gutters.
    gutter = max(250, min(380, int(w * 0.30)))
    canvas = cv2.copyMakeBorder(image, 0, 0, gutter, gutter, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    packet_x = gutter

    # Draw only declaration evidence on the package itself.
    rendered = []
    for region in regions:
        try:
            x1, y1, x2, y2 = _bbox_to_px(region["bbox"], w, h)
        except Exception:
            continue
        if x2 <= x1 or y2 <= y1:
            continue
        status = str(region.get("status") or "DETECTED").upper()
        color = (0, 160, 0) if status == "PASS" else (0, 0, 210) if status == "FAIL" else (0, 150, 220)
        cv2.rectangle(canvas, (packet_x + x1, y1), (packet_x + x2, y2), color, 3)
        rendered.append((region, (x1, y1, x2, y2), color))

    # Put callouts in the left/right whitespace. Each side is vertically packed
    # with guaranteed spacing, so captions never sit on top of one another.
    side_groups = {"left": [], "right": []}
    packet_mid = w / 2
    for region, box, color in rendered:
        side = "left" if ((box[0] + box[2]) / 2) < packet_mid else "right"
        side_groups[side].append((region, box, color))

    for side, group in side_groups.items():
        group.sort(key=lambda item: (item[1][1] + item[1][3]) / 2)
        cursor = 12
        for region, box, color in group:
            title, value = _label_content(region)
            # Estimate height before drawing; enough separation for 2 value lines.
            lines = 1 + (min(2, len(_wrap_text(value[:80], 30))) if value else 0)
            lh = 14 + 17 * lines + 10
            desired = int((box[1] + box[3]) / 2 - lh / 2)
            label_y = max(cursor, desired)
            label_y = min(label_y, h - lh - 12)
            _draw_callout(canvas, packet_x, 0, box, side, label_y, title, value, color, gutter, 0.48)
            cursor = label_y + lh + 12

    # Optional calibration marker is infrastructure, not a Legal Metrology
    # declaration. Mark it subtly only when present.
    if calibration and calibration.get("qr_bbox"):
        x1, y1, x2, y2 = calibration["qr_bbox"]
        cv2.rectangle(canvas, (packet_x + x1, y1), (packet_x + x2, y2), (255, 120, 0), 2)
        cv2.putText(canvas, "50 mm QR calibration reference", (packet_x + x1, max(18, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 120, 0), 1, cv2.LINE_AA)

    # Deliberately do NOT draw PDP or generic evidence boxes: the competition
    # annotation is now a focused Legal Metrology declaration map.
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if not cv2.imwrite(output_path, canvas):
        raise IOError("Failed to write annotated image")

    return {
        "path": output_path,
        "regions_annotated": len(rendered),
        "regions_detected": len(all_regions),
        "annotation_scope": "legal_metrology_declarations_only",
    }
