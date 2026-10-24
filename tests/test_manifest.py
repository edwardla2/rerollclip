import json
from pathlib import Path
import tempfile
import unittest

from clipthat_editor.engine import EditorError, parse_manifest


class ManifestTests(unittest.TestCase):
    def build(self, data):
        folder = tempfile.TemporaryDirectory()
        path = Path(folder.name) / "manifest.json"
        path.write_text(json.dumps(data))
        return folder, path

    def test_empty_clips_fails(self):
        holder, path = self.build({"schema_version": 1, "clips": []})
        self.addCleanup(holder.cleanup)
        with self.assertRaises(EditorError):
            parse_manifest(path, check_files=False)

    def test_simple_contract_passes(self):
        holder, path = self.build({"schema_version": 1, "style": "clean", "layout": "fit_blur",
                                   "clips": [{"file": "fake.mp4", "start_seconds": 0, "duration_seconds": 6}]})
        self.addCleanup(holder.cleanup)
        self.assertEqual(len(parse_manifest(path, check_files=False)["clips"]), 1)

    def test_bad_layout_fails(self):
        holder, path = self.build({"schema_version": 1, "layout": "portrait_magic",
                                   "clips": [{"file": "fake.mp4", "duration_seconds": 6}]})
        self.addCleanup(holder.cleanup)
        with self.assertRaises(EditorError):
            parse_manifest(path, check_files=False)

    def test_negative_start_fails(self):
        holder, path = self.build({"schema_version": 1,
                                   "clips": [{"file": "fake.mp4", "start_seconds": -2, "duration_seconds": 6}]})
        self.addCleanup(holder.cleanup)
        with self.assertRaises(EditorError):
            parse_manifest(path, check_files=False)


if __name__ == "__main__":
    unittest.main()
