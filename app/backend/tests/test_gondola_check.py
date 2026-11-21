"""Which góndola a photo shows (gondola_check): the rule, on the pilot's real reading and real planograms.

Reading 105 is the deodorant góndola's ideal render analyzed with catalog v4 (planogram_position_pilot.json); the second
góndola of the store carries the Salud Sexual planogram (planograms_seed.json). The store queries and the move endpoint
are covered in gondola_cases.py (HTTP suite).
Run: python -m unittest discover -s app/backend/tests -p "test_gondola_check.py"
"""
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gondola_check as gc  # noqa: E402

PILOT = json.loads((HERE / "planogram_position_pilot.json").read_text(encoding="utf-8"))
DEO = {"id": "deo", **PILOT["planogram"]}
SALUD = json.loads((HERE.parent / "planogramas" / "planograms_seed.json").read_text(encoding="utf-8"))[0]
PRODUCTS = PILOT["reading_105"]["products"]


def gondola(point_id, *planograms):
    return {"point_id": point_id, "name": point_id.upper(), "planograms": list(planograms)}


class GondolaCheckTests(unittest.TestCase):
    def test_a_deodorant_photo_on_the_salud_sexual_gondola_points_to_the_deodorant_one(self):
        recognized = gc.recognized_codes(PRODUCTS)
        in_deo = len(recognized & gc.planogram_codes(DEO))
        self.assertGreaterEqual(in_deo, 40)  # the ideal render: most recognized products are deodorant positions
        verdict = gc.check(PRODUCTS, gondola("g1", SALUD), [gondola("g2", DEO)])
        self.assertEqual((verdict["current_point_id"], verdict["current_matches"]), ("g1", 0))
        self.assertEqual((verdict["suggested_point_id"], verdict["suggested_name"], verdict["suggested_matches"]), ("g2", "G2", in_deo))
        self.assertEqual(verdict["suggested_planogram_id"], "deo")
        self.assertEqual(verdict["recognized"], len(recognized))

    def test_the_right_gondola_gets_no_suggestion(self):
        verdict = gc.check(PRODUCTS, gondola("g2", DEO), [gondola("g1", SALUD)])
        self.assertIsNone(verdict["suggested_point_id"])
        self.assertGreaterEqual(verdict["current_matches"], 40)

    def test_a_gondola_without_planogram_gets_a_suggestion_only_from_a_clear_winner(self):
        verdict = gc.check(PRODUCTS, gondola("g1"), [gondola("g2", DEO), gondola("g3")])
        self.assertEqual(verdict["suggested_point_id"], "g2")
        tie = gc.check(PRODUCTS, gondola("g1"), [gondola("g2", DEO), gondola("g3", DEO)])
        self.assertIsNone(tie["suggested_point_id"])  # two góndolas with the same planogram: cannot tell which

    def test_weak_evidence_is_no_suggestion(self):
        deo_codes = sorted(gc.planogram_codes({"items": DEO["items"][:4]}))
        four = [{"match_status": "match", "sku": c} for c in deo_codes[:4]]
        self.assertIsNone(gc.check(four, gondola("g1", SALUD), [gondola("g2", DEO)])["suggested_point_id"])
        # the current góndola explains half of what was recognized: no suggestion, even if another explains more
        items = DEO["items"]
        half = {"id": "half", "items": items[:10]}
        products = [{"match_status": "match", "sku": it["internal_code"]} for it in items[:20]]
        verdict = gc.check(products, gondola("g1", half), [gondola("g2", DEO)])
        self.assertEqual((verdict["current_matches"], verdict["suggested_point_id"]), (10, None))

    def test_unrecognized_products_and_lone_gondolas_give_no_verdict(self):
        self.assertIsNone(gc.check(PRODUCTS, gondola("g1", SALUD), []))
        self.assertIsNone(gc.check(PRODUCTS, gondola("g1", SALUD), [gondola("g1", DEO)]))  # itself is not another one
        unreadable = [{"match_status": "unmatched", "sku": ""}, {"match_status": "gap"}]
        self.assertIsNone(gc.check(unreadable, gondola("g1", SALUD), [gondola("g2", DEO)]))

    def test_codes_match_by_barcode_and_without_leading_zeros(self):
        item = next(it for it in DEO["items"] if it["barcode"] and it["internal_code"])
        products = [{"match_status": "confirmed", "sku": "", "barcode": "000" + item["barcode"]},
                    {"match_status": "match", "sku": "0" + item["internal_code"]}]
        self.assertEqual(gc.recognized_codes(products), {item["barcode"].lstrip("0"), item["internal_code"].lstrip("0")})
        self.assertEqual(len(gc.recognized_codes(products) & gc.planogram_codes(DEO)), 2)

    def test_every_new_reading_is_checked_before_it_is_stored(self):
        # core loads the engine, so the HTTP suite replaces it: this pins the wiring that suite cannot run
        source = (HERE.parent / "core.py").read_text(encoding="utf-8")
        body = source.split("def analyze_and_store(", 1)[1].split("\ndef ", 1)[0]
        aligned = body.index("level_alignment.align(analysis, planogram)")
        checked = body.index("gondola_check.check_reading(point_id, analysis.get(\"products\"), planogram)")
        self.assertLess(aligned, checked)
        self.assertLess(checked, body.index("db.add_reading("))
        self.assertIn('"gondola_check": verdict', body)


if __name__ == "__main__":
    unittest.main()
