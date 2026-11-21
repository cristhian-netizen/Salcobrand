"""The engine's shelf levels aligned with the planogram's bands.

The engine numbers levels from the top of the photo. A promotional banner over the góndola (pilot, L128 deodorants,
2026-11-19/20: shampoo and L'Oréal ads, "del 29 de octubre al 25 de noviembre") was read as level 1 and every real
shelf came one level down: band 1's products on level 2, false stock-outs on the banner, compliance comparing each
shelf with the band above it. The products the engine recognizes by code say where each band is in the photo: on the
three photos with the banner 22 of 32, 4 of 6 and 6 of 10 of them sat exactly one level below their band; on a photo
without it, 9 of 16 sat on it.

Rule (align):
- Each product whose sku or barcode is a single planogram position votes level - band. The offset is the most voted
  value when it has at least MIN_VOTES votes, at least half of them, and no tie. Otherwise nothing changes.
- With a positive offset, or more levels than bands, some levels fall outside the planogram: above band 1 (the
  banner) or below the last band (an empty base deck). They are dropped only when the planogram recognizes almost
  nothing on them (a banner prints a product or two). An outside level carrying real planogram products means
  something else (a shelf split in two, the wrong planogram): then nothing changes.
- Kept levels are renumbered to their bands. A negative offset (the photo starts below band 1) changes nothing.
- What was dropped, and the evidence, stays in engine["level_alignment"], so it can be audited and undone.
"""
from collections import Counter

MIN_VOTES = 3
OUTSIDE_MAX_KNOWN = 0.15  # an outside level may carry max(1, 15 % of its detections) planogram products


def _code(value):
    text = str(value or "").strip()
    return text.lstrip("0") or text if text else ""


def _level(product):
    level = product.get("shelf_level") if isinstance(product, dict) else None
    return level if type(level) is int and level >= 1 else None


def _bands_by_code(planogram):
    found = {}
    for item in planogram.get("items") or []:
        band = item.get("band")
        if type(band) is not int:
            continue
        for raw in (item.get("internal_code"), item.get("barcode")):
            code = _code(raw)
            if code:
                found.setdefault(code, set()).add(band)
    return found


def _bands_of(product, by_code):
    for raw in (product.get("sku"), product.get("barcode")):
        bands = by_code.get(_code(raw))
        if bands:
            return bands
    return None


def offset_votes(products, by_code):
    """Counter of level - band over the products whose code is exactly one planogram band."""
    votes = Counter()
    for p in products:
        level, bands = _level(p), _bands_of(p, by_code)
        if level is not None and bands and len(bands) == 1:
            votes[level - next(iter(bands))] += 1
    return votes


def _offset(votes):
    if not votes:
        return None
    ranked = votes.most_common()
    offset, count = ranked[0]
    if count < MIN_VOTES or count * 2 < sum(votes.values()) or (len(ranked) > 1 and ranked[1][1] == count):
        return None
    return offset


def dominant_offset(products, planogram):
    """The level - band offset that the products recognized by code agree on (the rule of align), or None without
    clear evidence. 0 when the photo's levels already are the planogram's bands."""
    if not isinstance(planogram, dict):
        return None
    return _offset(offset_votes(products or [], _bands_by_code(planogram)))


def align(analysis, planogram):
    """`analysis` with its levels aligned to the planogram's bands (a new dict), or the same dict when there is
    nothing to align or not enough evidence."""
    if not isinstance(analysis, dict) or not isinstance(planogram, dict):
        return analysis
    bands = planogram.get("bands")
    products = analysis.get("products") or []
    levels = sorted({_level(p) for p in products} - {None})
    if type(bands) is not int or bands < 1 or not levels:
        return analysis
    by_code = _bands_by_code(planogram)
    votes = offset_votes(products, by_code)
    offset = _offset(votes)
    if offset is None or offset < 0:
        return analysis
    outside = [lv for lv in levels if not 1 <= lv - offset <= bands]
    if offset == 0 and not outside:
        return analysis
    evidence = {"bands": bands, "levels_before": len(levels), "offset": offset,
                "votes": {str(k): v for k, v in sorted(votes.items())}}
    for lv in outside:
        on_level = [p for p in products if _level(p) == lv]
        detections = sum(1 for p in on_level if p.get("match_status") != "gap")
        known = sum(1 for p in on_level if _bands_of(p, by_code))
        if known > max(1, OUTSIDE_MAX_KNOWN * detections):
            engine = dict(analysis.get("engine") or {})
            engine["level_alignment"] = {**evidence, "applied": False, "outside_levels": outside,
                                         "reason": f"el nivel {lv} queda fuera del planograma pero tiene {known} productos del planograma"}
            return {**analysis, "engine": engine}

    kept, dropped = [], []
    for p in products:
        level = _level(p)
        if level in outside:
            dropped.append(p)
        else:
            kept.append({**p, "shelf_level": level - offset} if level is not None else p)
    dropped_facings = sum(p.get("facings") or 0 for p in dropped)
    gaps_before = sum(1 for p in products if p.get("match_status") == "gap")
    gaps_after = sum(1 for p in kept if p.get("match_status") == "gap")
    levels_after = len(levels) - len(outside)

    result = {**analysis, "products": kept}
    if isinstance(analysis.get("total_facings"), (int, float)):
        result["total_facings"] = max(0, analysis["total_facings"] - dropped_facings)
    if isinstance(analysis.get("shelf_levels_detected"), int):
        result["shelf_levels_detected"] = max(0, analysis["shelf_levels_detected"] - len(outside))
    empty = analysis.get("empty_space_pct")
    if isinstance(empty, (int, float)) and levels_after:
        # The engine measures gap width over (photo width x levels); without the widths here, every gap is taken as
        # equally wide: approximate, and much closer than counting the banner's gaps as empty shelf.
        share = gaps_after / gaps_before if gaps_before else 1.0
        result["empty_space_pct"] = round(min(100.0, max(0.0, empty * len(levels) / levels_after * share)), 1)
    categories = analysis.get("categories")
    if isinstance(categories, list) and len(categories) == 1 and isinstance(categories[0], dict):
        result["categories"] = [{**categories[0], "total_facings": result.get("total_facings", categories[0].get("total_facings")),
                                 "product_count": len({p.get("product") for p in kept}),
                                 "brand_count": len({p.get("brand") for p in kept if p.get("brand")})}]
    above = sum(1 for lv in outside if lv - offset < 1)
    below = len(outside) - above
    what = [f"{n} fila{'s' if n != 1 else ''} {where}" for n, where in
            ((above, "sobre la góndola (cartel)"), (below, "bajo la última banda (base)")) if n]
    note = f"Niveles alineados al planograma ({bands} bandas)"
    note += f": se descartó {' y '.join(what)}, {len(dropped)} detecciones." if what else "."
    result["notes"] = " ".join(t for t in (analysis.get("notes") or "", note) if t)
    engine = dict(analysis.get("engine") or {})
    engine["level_alignment"] = {**evidence, "applied": True, "dropped_levels": outside, "levels_after": levels_after,
                                 "dropped": dropped, "total_facings_before": analysis.get("total_facings"),
                                 "shelf_levels_before": analysis.get("shelf_levels_detected"),
                                 "empty_space_pct_before": empty, "empty_space_approximate": bool(outside)}
    result["engine"] = engine
    return result
