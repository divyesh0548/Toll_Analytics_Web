"""Captcha OCR helpers used by IHMCL bots.

Requires pytesseract + Tesseract OCR installed on the machine.
"""

from __future__ import annotations

import re


def extract_text(image_array):
    """
    Extract text candidates from a captcha image (numpy RGB array).
    Returns a list of strings (best-effort).
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        raise ImportError(
            "ocr_module requires pytesseract and Pillow. "
            "Install with: pip install pytesseract pillow"
        ) from exc

    img = Image.fromarray(image_array)
    raw = pytesseract.image_to_string(img, config="--psm 7")
    cleaned = special_character_remover(raw)
    if cleaned:
        return [cleaned]
    # Fallback: return raw tokens
    tokens = [t.strip() for t in re.split(r"\s+", raw) if t.strip()]
    return tokens or [""]


def special_character_remover(text: str) -> str:
    if text is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(text)).strip()
