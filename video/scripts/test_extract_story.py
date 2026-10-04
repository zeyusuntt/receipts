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

    def test_scale_and_printed_receipt_fields_come_from_run_records(self):
        CHECKS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CHECKS) as tmp:
            out = Path(tmp) / "story.json"
            result = self.extract(out)
            self.assertEqual(result.returncode, 0, result.stderr)
            story = json.loads(out.read_text())

            self.assertEqual(story["numbers"]["repos"], 100)
            self.assertEqual(
                story["numbers"]["scale"],
                {"tokens": 87_379_659, "sandboxes": 482, "steps": 4_253},
            )
            self.assertEqual(story["featured"]["revision"], "ac8a91a")
            self.assertEqual(
                story["featured"]["receipt"],
                {
                    "target_tests": 3,
                    "kept_tests": 333,
                    "collected_tests": 342,
                    "removed_or_skipped": 0,
                    "files_changed": 2,
                    "test_files_changed": 0,
                    "agent_steps": 36,
                    "witness_steps": 2,
                    "attempts": [
                        {"number": 1, "verdict": "rejected"},
                        {"number": 2, "verdict": "verified"},
                    ],
                },
            )

    def test_featured_pr_description_comes_from_the_verified_run(self):
        CHECKS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CHECKS) as tmp:
            out = Path(tmp) / "story.json"
            result = self.extract(out)
            self.assertEqual(result.returncode, 0, result.stderr)

            description = json.loads(out.read_text())["featured"]["pr_description"]
            self.assertTrue(
                description.startswith(
                    "Fixes pyfilesystem__pyfilesystem2-462: FTPFS should use MDTM."
                )
            )
            self.assertIn(
                "Verified by Receipts on a fresh sandbox the agent never touched:",
                description,
            )
            self.assertIn(
                "re-verify: uv run receipts reverify "
                "receipts/pyfilesystem__pyfilesystem2-462.json",
                description,
            )

    def test_featured_witness_operations_select_the_longest_operation_per_branch(self):
        CHECKS.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=CHECKS) as tmp:
            out = Path(tmp) / "story.json"
            result = self.extract(out)
            self.assertEqual(result.returncode, 0, result.stderr)

            operations = json.loads(out.read_text())["featured"]["witness_operations"]
            self.assertEqual(
                operations,
                {
                    "w1": "01a0ff61-b8fb-77a8-a0a0-dc178108f719",
                    "w2": "01a0ff63-2a85-72ca-b4a5-6acd9e56af33",
                },
            )

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
