"""Offline regression checks for the video extraction boundary."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "video/scripts/extract_story.py"
PYTHON = ROOT / ".venv/bin/python"
CHECKS = ROOT / "video/out/checks"
FORBIDDEN = ("/opt/homebrew", "/opt/receipts-", "/Users/", "/private/")


class StoryExtractionTests(unittest.TestCase):
    def extract(self, out):
        return subprocess.run(
            [str(PYTHON), str(SCRIPT), "--repo", ".", "--out", str(out)],
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True,
            text=True,
        )

    def test_steps_expose_readable_site_commands_without_host_paths(self):
        CHECKS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CHECKS) as tmp:
            out = Path(tmp) / "story.json"
            result = self.extract(out)
            self.assertEqual(result.returncode, 0, result.stderr)
            written = out.read_text()
            steps = json.loads(written)["featured"]["agent_steps"]
            self.assertTrue(all(isinstance(step.get("display"), str) for step in steps))
            displays = [step["display"] for step in steps]
            self.assertIn('grep -n "_parse_ftp_time" fs/ftpfs.py', displays)
            self.assertIn("write fs/ftpfs.py", displays)
            self.assertIn("pytest tests/test_ftpfs.py -v --tb=no -q", displays)
            self.assertEqual(displays[-1], "capture patch")
            for prefix in FORBIDDEN:
                self.assertNotIn(prefix, written)

    def test_forbidden_paths_in_preserved_copy_fail_before_overwriting(self):
        CHECKS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CHECKS) as tmp:
            out = Path(tmp) / "story.json"
            for prefix in FORBIDDEN:
                with self.subTest(prefix=prefix):
                    previous = json.dumps({"presentation": {"nested": [prefix + "secret"]}})
                    out.write_text(previous)
                    result = self.extract(out)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("refusing to write", result.stderr)
                    self.assertEqual(out.read_text(), previous)


if __name__ == "__main__":
    unittest.main()
