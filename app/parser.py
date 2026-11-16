"""Pharmacy supplier-bill parser.

Parses pasted/typed bill text (and CSV-like lines). OCR via Tesseract is
used ONLY if the `tesseract` binary is actually installed — otherwise the
caller is told plainly that OCR is unavailable and text input is required.
Never pretends to have read a photo.
"""
import re
import shutil

LINE_PATTERNS = [
    # "Paracetamol 500mg x 100 @ 12.50 = 1250" / "Name 100 x 12.50"
    re.compile(
        r"^(?P<name>.+?)\s*[x×]\s*(?P<qty>\d+)\s*(?:@|at|PKR|Rs\.?)?\s*(?P<price>[\d,]+(?:\.\d+)?)"
        r"(?:\s*=\s*(?P<total>[\d,]+(?:\.\d+)?))?\s*$",
        re.IGNORECASE,
    ),
    # "Paracetamol 500mg, 100, 12.50" or "Name | 100 | 12.50 | 1250"
    re.compile(
        r"^(?P<name>[^,|;]+?)\s*[,|;]\s*(?P<qty>\d+)\s*[,|;]\s*(?P<price>[\d,]+(?:\.\d+)?)"
        r"(?:\s*[,|;]\s*(?P<total>[\d,]+(?:\.\d+)?))?\s*$"
    ),
    # "100 x Paracetamol 500mg @ 12.50"
    re.compile(
        r"^(?P<qty>\d+)\s*[x×]\s*(?P<name>.+?)\s*(?:@|at|PKR|Rs\.?)?\s*(?P<price>[\d,]+(?:\.\d+)?)"
        r"(?:\s*=\s*(?P<total>[\d,]+(?:\.\d+)?))?\s*$",
        re.IGNORECASE,
    ),
]

HEADER_WORDS = {"item", "medicine", "product", "description", "qty", "quantity",
                "price", "rate", "amount", "total", "name", "sr", "s.no", "no"}


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def _num(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", "").strip())
    except ValueError:
        return None


def parse_bill_text(text: str) -> dict:
    """Parse bill text into items. Returns {items, total_pkr, unparsed_lines}."""
    items, unparsed = [], []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        words = {w.strip().lower() for w in re.split(r"[,|;]", line)}
        if words and words <= HEADER_WORDS:
            continue  # header row
        if re.match(r"^(total|grand total|subtotal|amount due|balance)\b", line, re.IGNORECASE):
            continue
        matched = None
        for pat in LINE_PATTERNS:
            m = pat.match(line)
            if m:
                matched = m
                break
        if not matched:
            unparsed.append(line)
            continue
        name = matched.group("name").strip(" -–—")
        qty = int(matched.group("qty"))
        price = _num(matched.group("price"))
        total = _num(matched.group("total"))
        if price is None or qty <= 0:
            unparsed.append(line)
            continue
        if total is None:
            total = round(qty * price, 2)
        items.append({
            "name": name,
            "qty": qty,
            "unit_price_pkr": price,
            "line_total_pkr": total,
        })
    total_pkr = round(sum(i["line_total_pkr"] for i in items), 2)
    return {"items": items, "total_pkr": total_pkr, "unparsed_lines": unparsed}


def ocr_image_bytes(data: bytes) -> dict:
    """OCR an uploaded bill photo — only if tesseract exists.

    Returns {"ok": False, "error": ...} when OCR is unavailable, so the
    caller can say so honestly instead of pretending.
    """
    if not ocr_available():
        return {
            "ok": False,
            "error": "OCR is not installed on this machine (no `tesseract` binary found). "
                     "Paste or type the bill text instead — the photo was not read.",
        }
    import subprocess
    import tempfile
    import os
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(data)
        path = f.name
    try:
        out = subprocess.run(
            ["tesseract", path, "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=120,
        )
        return {"ok": True, "text": out.stdout, "ocr_used": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"OCR failed: {exc}"}
    finally:
        os.unlink(path)
