"""Which góndola of the store a reading's photo shows, judged from the products the engine recognized.

In Escanear the replenisher picks the góndola (G1, G2...) before taking the photo; picking the wrong one compares the
photo with the wrong planogram. After the analysis the recognized products tell which planogram the photo belongs to:
every góndola of the same store is scored by how many of the distinct recognized products (by sku or barcode, codes
compared like compute_planogram_compliance: stripped, without leading zeros) are positions of its planograms. A góndola
is scored with the best of the planograms it is measured against: its own (points.planogram_id), the shared planograms
assigned to its store and góndola type, and the one of its latest reading; the current góndola also with the planogram
this reading was compared with.

Rule (check) — another góndola is suggested only with clear evidence:
- at least MIN_MATCHES distinct recognized products are in its planogram,
- at least RATIO times as many as the current góndola explains,
- the current góndola explains less than MAX_CURRENT_SHARE of the recognized products,
- and no other góndola of the store ties with it.
No other capturable góndola in the store, or nothing recognized: no verdict at all. A góndola without a planogram explains
nothing, so a reading without one only gets a suggestion when another góndola clearly wins.

move_reading moves a reading to the suggested (or any capturable) góndola of the same store and compares it with that
góndola's planogram that best explains the photo.
"""
import json

MIN_MATCHES = 5
RATIO = 2.0
MAX_CURRENT_SHARE = 0.5
RECOGNIZED = ("match", "confirmed")


def _code(value):
    text = str(value or "").strip()
    return text.lstrip("0") or text if text else ""


def recognized_codes(products) -> set:
    """Distinct codes of the products the engine (or a person) identified."""
    codes = set()
    for p in products or []:
        if not isinstance(p, dict) or p.get("match_status") not in RECOGNIZED:
            continue
        for raw in (p.get("sku"), p.get("barcode")):
            code = _code(raw)
            if code:
                codes.add(code)
                break
    return codes


def planogram_codes(planogram) -> set:
    codes = set()
    for item in (planogram or {}).get("items") or []:
        for raw in (item.get("internal_code"), item.get("barcode")):
            code = _code(raw)
            if code:
                codes.add(code)
    return codes


def _score(gondola, recognized):
    best, best_plan = 0, None
    for planogram in gondola.get("planograms") or []:
        n = len(recognized & planogram_codes(planogram))
        if n > best:
            best, best_plan = n, planogram
    return best, best_plan


def check(products, current, candidates):
    """current / candidates: {"point_id", "name", "planograms": [planogram dicts]}. Returns the verdict stored in
    engine["gondola_check"], or None when there is nothing to compare."""
    others = [g for g in candidates or [] if g.get("point_id") and g["point_id"] != current.get("point_id")]
    recognized = recognized_codes(products)
    if not others or not recognized:
        return None
    current_n, _ = _score(current, recognized)
    scored = sorted(((_score(g, recognized), g) for g in others), key=lambda entry: -entry[0][0])
    (best_n, best_plan), best = scored[0]
    tie = len(scored) > 1 and scored[1][0][0] == best_n
    verdict = {"current_point_id": current.get("point_id"), "current_matches": current_n, "recognized": len(recognized),
               "suggested_point_id": None, "suggested_name": None, "suggested_matches": None, "suggested_planogram_id": None}
    if (best_n >= MIN_MATCHES and best_n >= RATIO * current_n and current_n < MAX_CURRENT_SHARE * len(recognized)
            and not tie):
        verdict.update(suggested_point_id=best["point_id"], suggested_name=best.get("name") or best["point_id"],
                       suggested_matches=best_n, suggested_planogram_id=(best_plan or {}).get("id"))
    return verdict


# ------------------------------------------------------------------------------------------------ store góndolas

def _plan_ids(conn, point, annotated):
    import plan_assignments
    ids = []
    if point.get("planogram_id"):
        ids.append(point["planogram_id"])
    type_id = ((annotated or {}).get("infrastructure") or {}).get("type_id")
    if point.get("store_id") and type_id:
        ids += [r["plan_id"] for r in plan_assignments.available(conn, point["store_id"], type_id=type_id)]
    row = conn.execute("SELECT planogram_id FROM readings WHERE point_id = ? AND planogram_id IS NOT NULL ORDER BY id DESC LIMIT 1",
                       (point["id"],)).fetchone()
    if row and row["planogram_id"]:
        ids.append(row["planogram_id"])
    return list(dict.fromkeys(ids))


def _gondolas(point_id, extra_planogram=None):
    """(current, others) for check(): the góndolas of the point's store (only capturable ones as candidates)."""
    import db
    import infrastructure
    with db.get_conn() as conn:
        row = conn.execute("SELECT * FROM points WHERE id = ?", (point_id,)).fetchone()
        if not row:
            return None, []
        point = dict(row)
        rows = [dict(r) for r in conn.execute("SELECT * FROM points WHERE store_id = ? AND id != ?", (point.get("store_id"), point_id)).fetchall()] \
            if point.get("store_id") else []
        rows = [r for r in rows if not r["id"].startswith("SB-MANUAL-")]
        annotated = {p["id"]: p for p in infrastructure.annotate_points([point, *rows])}
        plans, cache = {}, {}
        for p in [point, *rows]:
            plans[p["id"]] = _plan_ids(conn, p, annotated.get(p["id"]))

    def load(plan_id):
        if plan_id not in cache:
            cache[plan_id] = db.get_planogram(plan_id)
        return cache[plan_id]

    def gondola(p):
        return {"point_id": p["id"], "name": p.get("name") or p["id"],
                "planograms": [pg for pg in (load(i) for i in plans[p["id"]]) if pg]}

    current = gondola(point)
    if extra_planogram:
        current["planograms"].insert(0, extra_planogram)
    others = [gondola(p) for p in rows if annotated.get(p["id"], {}).get("can_capture")]
    return current, others


def check_reading(point_id, products, planogram=None):
    """Verdict for a new reading of point_id compared with `planogram` (None when there is nothing to compare)."""
    current, others = _gondolas(point_id, planogram)
    if current is None:
        return None
    return check(products, current, others)


# ------------------------------------------------------------------------------------------------ move

def move_reading(reading_id, target_point_id, actor):
    """Move a reading to another capturable góndola of the same store. The reading is compared with the target's
    planogram that best explains its recognized products (the suggested one when the check made the suggestion), its
    capture context takes the target's góndola data, the measurement review is reopened and the move is audited."""
    import db
    import infrastructure
    from infrastructure import ManagementError
    reading = db.get_reading(reading_id)
    if not reading:
        raise ManagementError("Lectura no encontrada", 404)
    source = reading["point_id"]
    if target_point_id == source:
        raise ManagementError("La medición ya está en esa góndola.", 409)
    _, source_store = db.point_store_id(source)
    exists, target_store = db.point_store_id(target_point_id)
    if not exists:
        raise ManagementError("Góndola no encontrada", 404)
    if not source_store or source_store != target_store:
        raise ManagementError("Solo se puede mover la medición a otra góndola del mismo local.", 409)
    target_context = infrastructure.capture_context(target_point_id)  # 409 when the target cannot be captured

    _, others = _gondolas(source)
    target = next((g for g in others if g["point_id"] == target_point_id), None)
    if target is None:
        raise ManagementError("Esa góndola no está disponible para mediciones.", 409)
    engine = dict(reading.get("engine") or {})
    verdict = dict(engine.get("gondola_check") or {})
    recognized = recognized_codes(reading.get("products"))
    planogram = None
    if verdict.get("suggested_point_id") == target_point_id and verdict.get("suggested_planogram_id"):
        planogram = next((pg for pg in target["planograms"] if pg.get("id") == verdict["suggested_planogram_id"]), None)
    if planogram is None:
        _, planogram = _score(target, recognized)
        if planogram is None and target["planograms"]:
            planogram = target["planograms"][0]
    plan_id = (planogram or {}).get("id")

    context = dict(reading.get("infrastructure") or {})
    for key in ("planogramClassification", "category", "subcategories", "subcategory"):
        context.pop(key, None)
    if target_context:
        context.update({k: v for k, v in target_context.items() if k != "id"})
        context["instance_id"] = target_context.get("id")
    if planogram and planogram.get("category"):
        classification = {"category": planogram["category"], "subcategories": planogram.get("subcategories", [])}
        context.update(planogramClassification=classification, **classification)
    linear_meters = reading.get("linear_meters")
    if context.get("captureMode") == "type" and target_context and target_context.get("width_cm"):
        linear_meters = target_context["width_cm"] / 100

    if verdict:
        verdict.update(suggested_point_id=None, suggested_name=None, suggested_matches=None, suggested_planogram_id=None)
        engine["gondola_check"] = verdict
    engine["moved"] = {"from": source, "to": target_point_id, "by": actor, "at": db.now_iso()}
    before = {"point_id": source, "planogram_id": reading.get("planogram_id")}
    after = {"point_id": target_point_id, "planogram_id": plan_id}
    with db.get_conn() as conn:
        conn.execute("UPDATE readings SET point_id = ?, planogram_id = ?, plan_snapshot_json = ?, capture_context_json = ?, "
                     "linear_meters = ?, engine_json = ? WHERE id = ?",
                     (target_point_id, plan_id, json.dumps(planogram) if planogram else None,
                      json.dumps(context) if context else None, linear_meters, json.dumps(engine), reading_id))
        db.invalidate_measurement_review(conn, reading_id)
        infrastructure._audit(conn, actor, "reading.move", str(reading_id), before, after)
    return db.get_reading(reading_id)
