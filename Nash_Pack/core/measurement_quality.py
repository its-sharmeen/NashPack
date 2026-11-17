"""Image-quality gates for physical lettering measurement."""
from typing import Any, Dict
import cv2
import numpy as np


def blur_score(image) -> float:
    """Variance of Laplacian; higher generally means a sharper image."""
    if image is None or getattr(image, "size", 0) == 0:
        return 0.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def assess_image_quality(image, min_blur: float = 80.0) -> Dict[str, Any]:
    score = blur_score(image)
    sharp = score >= float(min_blur)
    return {
        "blur_score": round(score, 2),
        "sharp_enough": sharp,
        "status": "GOOD" if sharp else "BLURRY",
        "threshold": float(min_blur),
        "reason": "Image has enough edge detail for measurement." if sharp else "Image is too soft for a defensible glyph-height measurement; refocus or capture again.",
    }


def frame_difference_score(previous_gray, current_gray) -> float:
    """Mean absolute pixel difference; lower means the camera is more stable."""
    if previous_gray is None or current_gray is None:
        return float("inf")
    if previous_gray.shape != current_gray.shape:
        current_gray = cv2.resize(current_gray, (previous_gray.shape[1], previous_gray.shape[0]))
    return float(np.mean(cv2.absdiff(previous_gray, current_gray)))
