"""Positions auto-detected in Salcobrand's planogram PDFs (the text export of a .plnx planogram).

Line grammar validated in the NeuraVision engine on 4 real Salcobrand planograms (379 products): a section header
``module/band`` (``1/4``), then one row per product with position, title, internal code, barcode and facings, plus
tag words (TOP / LANZAMIENTO) and wrapped title fragments on the following lines. The engine reads the text with
``pdftotext -layout``; this server has no system binaries, so the same lines come from pypdf's layout mode, which
also keeps one physical row per line. Scanned PDFs (no text layer) and other layouts simply yield no items.
"""
from __future__ import annotations

import io
import re

SECTION_RE = re.compile(r"^\s*(\d+)[/.](\d+)\s*$")
ROW_RE = re.compile(r"^\s*(\d{1,2})\s+(\S.*)$")
TAG_FRAGMENTS = {"TOP", "LANZA", "MIENT", "O", "LANZAMIENTO", "MIENTO", "15", "5", "6", "7", "8"}
MAX_PAGES = 60  # Salcobrand planograms have 6-12 pages; anything larger is not one


def _is_code(token: str) -> bool:
    return token.isdigit() and len(token) >= 3


def _checksum_ok(digits: str) -> bool:
    """GTIN check digit (same modulo-10 weighting for EAN-13 and GTIN-14)."""
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(reversed(digits[:-1]), 1))
    return (10 - total % 10) % 10 == int(digits[-1])


def _split_merged(token: str) -> list:
    """pypdf occasionally glues the barcode column to the next one: a 14-digit token whose 13-digit prefix is a
    valid EAN-13 while the whole is not a valid GTIN-14 is split back into barcode plus the trailing digit."""
    if len(token) == 14 and token.isdigit() and not _checksum_ok(token) and _checksum_ok(token[:13]):
        return [token[:13], token[13:]]
    return [token]


def extract_text(content: bytes) -> str:
    """Layout-mode text of the PDF, or '' when it cannot be a Salcobrand planogram (encrypted, huge, no text)."""
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted or not 1 <= len(reader.pages) <= MAX_PAGES:
        return ""
    return "\n".join(page.extract_text(extraction_mode="layout") for page in reader.pages)


def parse_pdf_bytes(content: bytes) -> dict:
    """{name, module_cm, bands, items: [{position_in_section, band, title, internal_code, barcode,
    expected_facings, tag}]}. Items come out empty when the PDF does not follow Salcobrand's format."""
    items, band, started, module_cm, title_line = [], None, False, None, None
    for raw in extract_text(content).splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        m_cm = re.search(r"\b(\d{2,3})\s*cm\b", line)
        if m_cm and module_cm is None:
            module_cm = int(m_cm.group(1))
        if title_line is None and line.strip().endswith(".plnx"):
            title_line = line.strip()[:-5].strip()
        m = SECTION_RE.match(line)
        if m:
            band = int(m.group(2))
            started = True
            continue
        if not started:
            continue
        tokens = line.split()
        m = ROW_RE.match(line)
        if m and tokens[0].isdigit() and not _is_code(tokens[0]) and int(tokens[0]) <= 60 and any(_is_code(t) and len(t) >= 8 for t in tokens):
            idx = int(tokens[0])
            rest = [piece for token in tokens[1:] for piece in _split_merged(token)]
            first_code = next(i for i, t in enumerate(rest) if _is_code(t))
            title = " ".join(rest[:first_code])
            nums = [t for t in rest[first_code:] if t.isdigit()]
            tail = [t for t in rest[first_code:] if not t.isdigit()]
            barcode = max((n for n in nums if len(n) >= 8), key=len, default=None)
            facings, code, tag_nums = None, None, []
            for n in nums:
                if n == barcode:
                    continue
                if len(n) <= 2 and facings is None:
                    facings = int(n)
                elif len(n) <= 2:
                    tag_nums.append(n)
                elif len(n) >= 3:
                    code = n
            items.append({"position_in_section": idx, "band": band, "title": title, "internal_code": code, "barcode": barcode,
                          "expected_facings": facings or 1, "tag": " ".join(tail + tag_nums) or None})
            continue
        if not items:
            continue
        if len(tokens) == 1 and _is_code(tokens[0]):
            items[-1]["internal_code"] = items[-1]["internal_code"] or tokens[0]
            continue
        if all(t in TAG_FRAGMENTS for t in tokens):
            items[-1]["tag"] = ((items[-1]["tag"] or "") + " " + " ".join(tokens)).strip()
            continue
        if len(tokens) <= 4 and all(t.isupper() or any(c.isdigit() for c in t) for t in tokens) and not any(_is_code(t) for t in tokens):
            if tokens[0] in {"TOP", "LANZAMIENTO"}:
                items[-1]["tag"] = ((items[-1]["tag"] or "") + " " + " ".join(tokens)).strip()
            else:
                items[-1]["title"] = items[-1]["title"] + " " + " ".join(tokens)
    seen, unique = set(), []
    for item in items:
        title = re.sub(r"\s+", " ", item["title"].strip().lstrip("'")).strip()
        title = re.sub(r"(\s+\d{1,2}(?:[./]\d{1,2})+)+$", "", title)
        title = re.sub(r"(\s+\d{1,2})+$", "", title).strip()
        if not title or title in seen:
            continue
        seen.add(title)
        item["title"] = title
        if item["tag"]:
            item["tag"] = re.sub(r"\s+", " ", item["tag"].replace("LANZA MIENT O", "LANZAMIENTO")).strip()
        unique.append(item)
    bands = max((item["band"] or 0) for item in unique) if unique else 0
    return {"name": title_line or "", "module_cm": module_cm, "bands": bands, "items": unique}
