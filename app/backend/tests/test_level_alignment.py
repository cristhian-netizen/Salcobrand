"""Shelf levels aligned with the planogram (level_alignment): the banner over the L128 góndola is not a shelf.

The pilot fixtures are the engine's real readings of that góndola and its real planogram (level_alignment_pilot.json).
Run: python -m unittest discover -s app/backend/tests -p "test_level_alignment.py"
"""
import json
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import level_alignment as la  # noqa: E402

PILOT = json.loads(Path(__file__).with_name("level_alignment_pilot.json").read_text(encoding="utf-8"))
PLANOGRAM = PILOT["planogram"]


def pilot_analysis(reading_id):
    r = PILOT["readings"][str(reading_id)]
    products = [{"product": sku or f"{status} {i}", "brand": "", "sku": sku, "facings": facings, "shelf_level": level,
                 "position_index": i + 1, "match_status": status, "out_of_stock": status == "gap",
                 "image_index": 0, "item_index": i} for i, (level, status, sku, facings) in enumerate(r["products"])]
    return {"products": products, "total_facings": r["total_facings"], "shelf_levels_detected": r["shelf_levels_detected"],
            "empty_space_pct": r["empty_space_pct"], "notes": "",
            "categories": [{"category": "Desodorantes", "total_facings": r["total_facings"], "share_pct": 100.0}],
            "engine": {"images": [], "kilby": {"job_id": f"vjob_{reading_id}"}}}


def levels(analysis):
    return sorted({p["shelf_level"] for p in analysis["products"]})


def offsets(analysis):
    return la.offset_votes(analysis["products"], la._bands_by_code(PLANOGRAM))


class PilotBannerTests(unittest.TestCase):
    def test_the_banner_row_is_dropped_on_the_three_pilot_photos(self):
        for reading_id, dropped_levels in ((104, [1]), (102, [1]), (103, [1, 8])):
            before = pilot_analysis(reading_id)
            after = la.align(before, PLANOGRAM)
            audit = after["engine"]["level_alignment"]
            self.assertTrue(audit["applied"], reading_id)
            self.assertEqual((audit["offset"], audit["dropped_levels"]), (1, dropped_levels), reading_id)
            self.assertEqual(levels(after), [1, 2, 3, 4, 5, 6], reading_id)
            self.assertEqual(after["shelf_levels_detected"], 6, reading_id)
            # every recognized product now sits on its band: the most voted offset is 0
            self.assertEqual(offsets(after).most_common(1)[0][0], 0, reading_id)
            self.assertEqual(Counter(offsets(after))[0], offsets(before)[1], reading_id)
            # the banner's detections are gone, kept for audit, and its gaps no longer count as empty shelf
            gone = [p for p in before["products"] if p["shelf_level"] in dropped_levels]
            self.assertEqual(len(audit["dropped"]), len(gone), reading_id)
            self.assertEqual(len(after["products"]) + len(gone), len(before["products"]), reading_id)
            self.assertEqual(after["total_facings"], before["total_facings"] - sum(p["facings"] for p in gone), reading_id)
            self.assertEqual(after["categories"][0]["total_facings"], after["total_facings"], reading_id)
            gaps_gone = sum(p["out_of_stock"] for p in gone)
            self.assertGreater(gaps_gone, 0, reading_id)
            self.assertLess(after["empty_space_pct"], before["empty_space_pct"], reading_id)
            self.assertIn("sobre la góndola (cartel)", after["notes"], reading_id)
            self.assertEqual(after["engine"]["kilby"], before["engine"]["kilby"], reading_id)
        self.assertIn("bajo la última banda (base)", la.align(pilot_analysis(103), PLANOGRAM)["notes"])

    def test_the_input_is_not_modified(self):
        before = pilot_analysis(104)
        snapshot = json.dumps(before, sort_keys=True)
        la.align(before, PLANOGRAM)
        self.assertEqual(json.dumps(before, sort_keys=True), snapshot)

    def test_photos_without_the_banner_are_left_alone(self):
        for reading_id in (97, 101):  # 97: recognized products on their bands; 101: nothing recognized by code
            analysis = pilot_analysis(reading_id)
            self.assertIs(la.align(analysis, PLANOGRAM), analysis, reading_id)

    def test_every_new_reading_is_aligned_before_it_is_stored(self):
        # core loads the engine, so the HTTP suite replaces it: this pins the wiring that suite cannot run
        source = (Path(__file__).resolve().parents[1] / "core.py").read_text(encoding="utf-8")
        body = source.split("def analyze_and_store(", 1)[1].split("\ndef ", 1)[0]
        self.assertLess(body.index("level_alignment.align(analysis, planogram)"), body.index("db.add_reading("))
        self.assertIn("plan_snapshot if plan_snapshot is not None else db.get_planogram(planogram_id)", body)


PLAN = {"bands": 3, "items": [{"title": f"P{b}{i}", "band": b, "internal_code": f"{b}{i}0", "barcode": f"77{b}{i}"}
                              for b in (1, 2, 3) for i in range(1, 6)]}


def shelf(level, codes, gaps=0, unknown=0):
    rows = [{"product": c, "sku": c, "facings": 1, "shelf_level": level, "match_status": "match"} for c in codes]
    rows += [{"product": "?", "sku": "", "facings": 1, "shelf_level": level, "match_status": "unmatched"}] * unknown
    rows += [{"product": None, "sku": "", "facings": 0, "shelf_level": level, "match_status": "gap", "out_of_stock": True}] * gaps
    return rows


def analysis_of(*rows):
    products = [dict(p) for row in rows for p in row]
    return {"products": products, "total_facings": sum(p["facings"] for p in products),
            "shelf_levels_detected": len({p["shelf_level"] for p in products if p.get("shelf_level")}), "empty_space_pct": 5.0}


class SafetyTests(unittest.TestCase):
    def test_an_empty_base_deck_under_the_last_band_is_dropped(self):
        before = analysis_of(shelf(1, ["110", "120"]), shelf(2, ["210", "220"]), shelf(3, ["310", "320"]),
                             shelf(4, [], gaps=2, unknown=1))
        after = la.align(before, PLAN)
        self.assertEqual((after["engine"]["level_alignment"]["dropped_levels"], levels(after)), ([4], [1, 2, 3]))
        self.assertIn("bajo la última banda (base)", after["notes"])

    def test_a_level_outside_the_planogram_with_real_products_changes_nothing(self):
        # a shelf split in two (or the wrong planogram): level 1 carries band-1 products, the rest vote one level down
        before = analysis_of(shelf(1, ["110", "120", "130"]), shelf(2, ["140", "150"]), shelf(3, ["210", "220", "230"]),
                             shelf(4, ["310", "320", "330"]))
        after = la.align(before, PLAN)
        self.assertEqual(after["products"], before["products"])
        audit = after["engine"]["level_alignment"]
        self.assertFalse(audit["applied"])
        self.assertIn("el nivel 1", audit["reason"])

    def test_a_banner_that_prints_one_product_is_still_a_banner(self):
        before = analysis_of(shelf(1, ["220"], unknown=8), shelf(2, ["110", "120"]), shelf(3, ["210", "230"]),
                             shelf(4, ["310", "320"]))
        after = la.align(before, PLAN)
        self.assertEqual((after["engine"]["level_alignment"]["dropped_levels"], levels(after)), ([1], [1, 2, 3]))

    def test_weak_or_split_evidence_changes_nothing(self):
        cases = {
            "two votes": analysis_of(shelf(1, [], unknown=5), shelf(2, ["110"]), shelf(3, ["210"])),
            "tie": analysis_of(shelf(1, ["110", "120", "130"]), shelf(2, ["140"]), shelf(3, ["210", "220"])),
            "no majority": analysis_of(shelf(1, ["110", "120", "130"]), shelf(2, ["140", "310", "320"]),
                                       shelf(3, ["150", "330"]), shelf(4, ["340", "350"])),
        }
        for name, before in cases.items():
            self.assertIs(la.align(before, PLAN), before, name)

    def test_a_photo_that_starts_below_band_one_is_not_renumbered(self):
        before = analysis_of(shelf(1, ["210", "220"]), shelf(2, ["310", "320", "330"]))
        self.assertIs(la.align(before, PLAN), before)

    def test_missing_planogram_bands_or_levels_change_nothing(self):
        before = analysis_of(shelf(1, [], unknown=4), shelf(2, ["110", "120"]), shelf(3, ["210", "220"]), shelf(4, ["310"]))
        for planogram in (None, {}, {"bands": None, "items": PLAN["items"]}, {"bands": 0, "items": PLAN["items"]},
                          {"bands": 3, "items": []}):
            self.assertIs(la.align(before, planogram), before, planogram)
        empty = {"products": [], "total_facings": 0}
        self.assertIs(la.align(empty, PLAN), empty)
        self.assertIsNone(la.align(None, PLAN))

    def test_products_without_a_level_are_kept_and_leading_zeros_match(self):
        before = analysis_of(shelf(1, [], unknown=6), shelf(2, ["0110", "120"]), shelf(3, ["210", "0220"]),
                             shelf(4, ["310"]), [{"product": "suelto", "sku": "", "facings": 1, "shelf_level": None,
                                                 "match_status": "unmatched"}])
        before["categories"] = ["Salud sexual"]  # categories as plain names are left as they are
        after = la.align(before, PLAN)
        self.assertEqual(levels({"products": [p for p in after["products"] if p["shelf_level"]]}), [1, 2, 3])
        self.assertIn({"product": "suelto", "sku": "", "facings": 1, "shelf_level": None, "match_status": "unmatched"},
                      after["products"])
        self.assertEqual(after["categories"], ["Salud sexual"])
        self.assertEqual(after["total_facings"], before["total_facings"] - 6)


if __name__ == "__main__":
    unittest.main()
