"""Known-size QR reference calibration for SIH26034.

The printed QR symbol is the physical reference.  Its configured symbol side
length is fixed (default 50 mm). OpenCV detects the four QR corners, then a
planar homography rectifies the package/reference plane so CV glyph heights can
be converted from pixels to millimetres.
"""
import os
from typing import Any, Dict, List
import cv2
import numpy as np

DEFAULT_QR_SIZE_MM = float(os.getenv("CALIBRATION_QR_SIZE_MM", "50.0"))
EXPECTED_PAYLOAD = os.getenv("CALIBRATION_QR_PAYLOAD", "SIH26034-QR-50MM")
RECTIFIED_QR_PX = 1000


def _candidate(pts: np.ndarray, payload: str, qr_size_mm: float) -> Dict[str, Any]:
    side_lengths = [float(np.linalg.norm(pts[(i + 1) % 4] - pts[i])) for i in range(4)]
    px_side = float(np.mean(side_lengths))
    area_px = abs(float(cv2.contourArea(pts.astype(np.float32))))
    return {
        "payload": payload,
        "corners": [[round(float(x), 3), round(float(y), 3)] for x, y in pts],
        "pixel_side": round(px_side, 3),
        "side_lengths_px": [round(x, 3) for x in side_lengths],
        "side_consistency": round(min(side_lengths) / max(side_lengths), 4) if max(side_lengths) else 0.0,
        "area_px2": round(area_px, 2),
        "mm_per_pixel": float(qr_size_mm) / px_side if px_side else None,
        "pixels_per_mm": px_side / float(qr_size_mm) if qr_size_mm else None,
        "bbox": [
            int(round(float(pts[:, 0].min()))), int(round(float(pts[:, 1].min()))),
            int(round(float(pts[:, 0].max()))), int(round(float(pts[:, 1].max())))
        ],
    }


def detect_qr_scale(image_path: str, qr_size_mm: float = DEFAULT_QR_SIZE_MM) -> Dict[str, Any]:
    image = cv2.imread(image_path)
    if image is None:
        return {"available": False, "status": "REVIEW_REQUIRED", "reason": "Image could not be loaded for QR calibration.", "qr_detected": False}

    detector = cv2.QRCodeDetector()
    payloads: List[str] = []
    points_list: List[np.ndarray] = []

    try:
        ok, decoded_info, points, _ = detector.detectAndDecodeMulti(image)
        if ok and points is not None:
            payloads = [str(x or "") for x in decoded_info]
            points_list = [p.reshape(4, 2).astype(np.float32) for p in points]
    except Exception:
        pass

    if not points_list:
        try:
            payload, points, _ = detector.detectAndDecode(image)
            if points is not None:
                payloads = [str(payload or "")]
                points_list = [points.reshape(4, 2).astype(np.float32)]
        except Exception:
            pass

    if not points_list:
        return {
            "available": False, "status": "REVIEW_REQUIRED",
            "reason": "No QR calibration reference was detected. Place the verified 50 mm QR reference on the same plane as the lettering.",
            "qr_detected": False, "qr_size_mm": float(qr_size_mm), "expected_payload": EXPECTED_PAYLOAD,
        }

    candidates = []
    for pts, payload in zip(points_list, payloads):
        if cv2.contourArea(pts) <= 0:
            continue
        candidates.append(_candidate(pts, payload, qr_size_mm))

    if not candidates:
        return {"available": False, "status": "REVIEW_REQUIRED", "reason": "QR was detected but its four-corner geometry could not be measured reliably.", "qr_detected": False}

    # Prefer the expected SIH reference payload; otherwise use the largest QR.
    matching = [c for c in candidates if c["payload"] == EXPECTED_PAYLOAD]
    best = max(matching or candidates, key=lambda x: x["area_px2"])
    src = np.array(best["corners"], dtype=np.float32)
    s = RECTIFIED_QR_PX - 1
    dst = np.array([[0, 0], [s, 0], [s, s], [0, s]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src, dst)
    px_per_mm_rectified = (RECTIFIED_QR_PX - 1) / float(qr_size_mm)

    payload_ok = best["payload"] == EXPECTED_PAYLOAD
    return {
        "available": True,
        "status": "CALIBRATED",
        "reason": "Known-size QR reference detected; four-corner geometry and planar homography used for calibration.",
        "qr_detected": True,
        "qr_payload": best["payload"],
        "payload_verified": payload_ok,
        "expected_payload": EXPECTED_PAYLOAD,
        "qr_size_mm": float(qr_size_mm),
        "qr_pixel_side": best["pixel_side"],
        "mm_per_pixel": best["mm_per_pixel"],
        "pixels_per_mm": best["pixels_per_mm"],
        "qr_bbox": best["bbox"],
        "qr_corners": best["corners"],
        "side_consistency": best["side_consistency"],
        "rectified_qr_px": RECTIFIED_QR_PX,
        "rectified_pixels_per_mm": px_per_mm_rectified,
        "homography": H.tolist(),
        "candidates": candidates,
    }

