"""Unit + integration tests for the KM PoC. Run: python -m unittest -v

Uses only the standard library and the default hashing embedder, so the
whole suite runs offline with no third-party dependencies.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from km.config import Config
from km.embeddings import HashingEmbedder, cosine
from km.ingest.spreadsheet import detect_header, _dedupe_headers
from km.lang import detect_language, expand_terms
from km.pipeline import build_index, search
from km.schema import Record
from km.tagging import parse_date, infer_category, tag


class TestSchema(unittest.TestCase):
    def test_stable_id_and_provenance(self):
        r = Record(title="T", raw_text="x", source_file="f.csv",
                   sheet="s", row_or_page="row 4")
        self.assertEqual(r.id, r.compute_id())
        self.assertIn("f.csv", r.provenance)
        self.assertIn("row 4", r.provenance)

    def test_roundtrip(self):
        r = Record(title="T", raw_text="body", source_file="f", category="War Room")
        r2 = Record.from_dict(r.to_dict())
        self.assertEqual(r2.id, r.id)
        self.assertEqual(r2.category, "War Room")


class TestTagging(unittest.TestCase):
    def test_dates(self):
        self.assertEqual(parse_date("dated 14-06-2025 at"), "2025-06-14")
        self.assertEqual(parse_date("on 2025/03/04"), "2025-03-04")
        self.assertEqual(parse_date("19 April 2025"), "2025-04-19")
        self.assertIsNone(parse_date("no date here"))

    def test_language_detection(self):
        self.assertEqual(detect_language("Letter to the President"), "eng")
        self.assertEqual(detect_language("राष्ट्रपती महोदयांना निमंत्रण आहे"), "mar")
        self.assertEqual(detect_language("Subject: क्वांटम मिशन and quantum park review"), "mixed")

    def test_category_from_text(self):
        self.assertEqual(infer_category("cabinet approved the scheme"), "Cabinet Decisions")
        self.assertEqual(infer_category("वॉर रूम आढावा"), "War Room")

    def test_tag_fills_metadata(self):
        r = Record(title="Letter to Hon'ble President", raw_text="dated 2025-02-11 Mumbai",
                   source_file="vip.csv")
        tag(r)
        self.assertEqual(r.date, "2025-02-11")
        self.assertIn("Mumbai", r.location)
        self.assertTrue(any("President" in e for e in r.entities))


class TestCrossLingual(unittest.TestCase):
    def test_expansion_bridges_scripts(self):
        aliases = expand_terms("letter to the president")
        joined = " ".join(aliases)
        self.assertIn("राष्ट्रपती", joined)
        self.assertIn("पत्र", joined)

    def test_semiconductor(self):
        self.assertIn("सेमीकंडक्टर", " ".join(expand_terms("semiconductor")))


class TestHeaderDetection(unittest.TestCase):
    def test_header_below_row_one(self):
        rows = [
            ["Announcement Tracker 2025", "", "", ""],  # merged title row
            ["confidential", "", "", ""],               # subtitle
            ["Sr", "Date", "Dept", "Detail"],           # real header (idx 2)
            ["1", "2025-01-01", "Home", "something"],
            ["2", "2025-02-01", "Finance", "another"],
        ]
        self.assertEqual(detect_header(rows), 2)

    def test_dedupe_headers(self):
        self.assertEqual(
            _dedupe_headers(["Status", "Status", "", "Date"]),
            ["Status", "Status_1", "col3", "Date"],
        )


class TestEmbedder(unittest.TestCase):
    def test_normalised_and_self_similar(self):
        emb = HashingEmbedder(dim=256)
        v = emb.embed("quantum technology park")
        self.assertAlmostEqual(cosine(v, v), 1.0, places=5)
        near = cosine(v, emb.embed("quantum technology centre"))
        far = cosine(v, emb.embed("water supply metro corridor"))
        self.assertGreater(near, far)


class TestEndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cfg = Config(
            db_path=os.path.join(cls.tmp, "idx.sqlite3"),
            data_dir="data", embedder="hashing",
        )
        cls.summary = build_index(cls.cfg)

    def test_indexed_expected_counts(self):
        self.assertGreaterEqual(self.summary["indexed"], 25)
        self.assertIn("scan", self.summary["by_source_type"])
        self.assertIn("letter", self.summary["by_source_type"])

    def _titles(self, query, **kw):
        res = search(self.cfg, query, **kw)
        return [h.record.title for h in res.hits], res

    def test_quantum_query(self):
        _titles, res = self._titles("Show me everything on Quantum")
        files = {h.record.source_file for h in res.hits}
        self.assertIn("scan_quantum_note.txt", files)
        self.assertIn("announcements_tracker.csv", files)

    def test_cross_lingual_president(self):
        # English query must retrieve Marathi/Hindi राष्ट्रपती records.
        _t, res = self._titles("Letters to the President in 2025",
                               filters={"date": ["2025-01-01", "2025-12-31"]})
        langs = {h.record.language for h in res.hits}
        # At least one non-English record surfaced from an English query.
        self.assertTrue({"mar", "hin", "mixed"} & langs)
        # The 2024 President letter must be excluded by the date filter.
        for h in res.hits:
            if h.record.date:
                self.assertTrue("2025" in h.record.date)

    def test_semiconductor_meeting(self):
        _t, res = self._titles("What meetings on semiconductor manufacturing?")
        files = {h.record.source_file for h in res.hits}
        self.assertIn("scan_cm_meeting_semiconductor.txt", files)

    def test_category_filter(self):
        _t, res = self._titles("पाणीपुरवठा", filters={"category": "War Room"})
        self.assertTrue(res.hits)
        for h in res.hits:
            self.assertEqual(h.record.category, "War Room")


if __name__ == "__main__":
    unittest.main()
