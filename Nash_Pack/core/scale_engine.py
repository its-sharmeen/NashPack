"""Physical scale sources for universal font measurement.

A single RGB image has no absolute scale by itself. This module therefore makes
that limitation explicit and supports multiple scale sources without changing
Gemini VLM: known package dimension, calibrated QR reference, or client-supplied
AR/world scale.
"""
from typing import Any, Dict, Optional
import cv2
import numpy as np


def package_dimension_scale(image, package_bbox, width_mm: Optional[float] = None, height_mm: Optional[float] = None):
    """Create a planar package calibration from a known physical dimension.

    The package/PDP rectangle is mapped to a metric rectified plane. This is a
    marker-free path and works for arbitrary package sizes, provided the supplied
    physical dimension is accurate and the selected rectangle represents the same
    planar face as the lettering.
    """
    if image is None or not package_bbox:
        return {"available": False, "status": "REVIEW_REQUIRED", "reason": "Package geometry or physical dimension unavailable."}
    x1, y1, x2, y2 = [float(v) for v in package_bbox]
    pxw, pxh = abs(x2-x1), abs(y2-y1)
    if pxw < 10 or pxh < 10:
        return {"available": False, "status": "REVIEW_REQUIRED", "reason": "Package geometry is too small for scale estimation."}
    if not width_mm and not height_mm:
        return {"available": False, "status": "REVIEW_REQUIRED", "reason": "A physical package dimension is required for absolute millimetre scale."}

    # Use a metric rectified plane at 5 px/mm. If both dimensions are supplied,
    # both contribute to the homography and provide a useful consistency check.
    ppm = 5.0
    target_w = max(20, int(round((float(width_mm) if width_mm else (float(height_mm) * pxw / pxh)) * ppm)))
    target_h = max(20, int(round((float(height_mm) if height_mm else (float(width_mm) * pxh / pxw)) * ppm)))
    src = np.array([[x1,y1],[x2,y1],[x2,y2],[x1,y2]], dtype=np.float32)
    dst = np.array([[0,0],[target_w-1,0],[target_w-1,target_h-1],[0,target_h-1]], dtype=np.float32)
    H = cv2.getPerspectiveTransform(src, dst)

    consistency = None
    if width_mm and height_mm:
        observed_ratio = pxw / max(pxh, 1e-6)
        known_ratio = float(width_mm) / max(float(height_mm), 1e-6)
        consistency = min(observed_ratio/known_ratio, known_ratio/observed_ratio)

    return {
        "available": True, "status": "CALIBRATED", "source": "KNOWN_PACKAGE_DIMENSION",
        "pixels_per_mm": ppm, "mm_per_pixel": 1.0/ppm,
        "rectified_pixels_per_mm": ppm,
        "package_bbox": [int(round(x1)),int(round(y1)),int(round(x2)),int(round(y2))],
        "known_width_mm": float(width_mm) if width_mm else None,
        "known_height_mm": float(height_mm) if height_mm else None,
        "rectified_width_px": target_w, "rectified_height_px": target_h,
        "homography": H.tolist(),
        "dimension_consistency": round(float(consistency),4) if consistency is not None else None,
        "reason": "Marker-free package-plane scale derived from supplied physical package dimension."
    }


def ar_scale(world_mm_per_pixel: Optional[float]):
    if world_mm_per_pixel is None or world_mm_per_pixel <= 0:
        return {"available": False, "status":"REVIEW_REQUIRED", "reason":"AR world scale was not supplied."}
    return {"available":True,"status":"CALIBRATED","source":"AR_WORLD_SCALE",
            "mm_per_pixel":float(world_mm_per_pixel),"pixels_per_mm":1.0/float(world_mm_per_pixel),
            "rectified_pixels_per_mm":1.0/float(world_mm_per_pixel),
            "reason":"Scale supplied by AR world geometry."}
