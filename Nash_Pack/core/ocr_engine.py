"""
OCR + Image Preprocessing Engine
---------------------------------
Takes a raw product-label image and returns cleaned OCR text plus
per-word bounding-box + confidence + pixel-height data (used later
for the font-size / readability heuristic).
"""
import cv2
import numpy as np
import pytesseract
from pytesseract import Output


def preprocess_image(image_path):
    """Return a list of preprocessed variants of the image.
    Running OCR against multiple variants and merging results
    substantially improves recall on real-world product labels
    (glossy packaging, curved surfaces, low contrast print, etc.)
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError("Could not read image. Please upload a valid JPG/PNG.")

    variants = []

    # 1. Upscaled grayscale (helps small print)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    scale = 2 if max(h, w) < 1600 else 1
    if scale > 1:
        gray_big = cv2.resize(gray, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    else:
        gray_big = gray
    variants.append(("gray", gray_big, scale))

    # 2. Adaptive threshold (binarized) - good for high-contrast printed text
    thresh = cv2.adaptiveThreshold(
        gray_big, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
    )
    variants.append(("adaptive_thresh", thresh, scale))

    # 3. Denoised + Otsu threshold - good for noisy/glossy packaging
    denoised = cv2.fastNlMeansDenoising(gray_big, h=15)
    _, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    variants.append(("otsu", otsu, scale))

    return variants, (h, w)


def run_ocr(image_path):
    """Run OCR across preprocessing variants, merge and de-duplicate text,
    and return combined raw text + word-level metadata used for the
    font-size / readability heuristic.
    """
    variants, (orig_h, orig_w) = preprocess_image(image_path)

    best_text = ""
    best_conf = -1
    all_word_data = []

    for name, variant_img, scale in variants:
        config = "--oem 3 --psm 6"
        text = pytesseract.image_to_string(variant_img, config=config)
        data = pytesseract.image_to_data(variant_img, config=config, output_type=Output.DICT)

        confidences = [int(c) for c in data["conf"] if c not in ("-1", -1)]
        avg_conf = sum(confidences) / len(confidences) if confidences else 0

        if len(text.strip()) > len(best_text.strip()) and avg_conf >= best_conf - 15:
            best_text = text
            best_conf = avg_conf

        n = len(data["text"])
        for i in range(n):
            word = data["text"][i].strip()
            if not word:
                continue
            conf = int(data["conf"][i]) if data["conf"][i] not in ("-1", -1) else 0
            height_px = int(data["height"][i]) / scale  # normalize back to original image scale
            all_word_data.append({
                "word": word,
                "conf": conf,
                "height_px": height_px,
                "source": name,
            })

    combined_text = best_text
    return {
        "text": combined_text,
        "words": all_word_data,
        "image_size": {"width": orig_w, "height": orig_h},
        "avg_confidence": round(best_conf, 1),
    }
