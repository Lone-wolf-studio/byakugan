"""Tests for the Python CLI's report formats and output handling."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

from byakugan.cli import main


class CliTests(unittest.TestCase):
    def test_scan_prints_text_and_json(self):
        with tempfile.TemporaryDirectory(prefix="byakugan-cli-") as directory:
            (Path(directory) / "main.py").write_text("pass\n", encoding="utf-8")

            text_output = StringIO()
            with redirect_stdout(text_output):
                self.assertEqual(main(["scan", directory]), 0)
            self.assertIn("Source files: 1", text_output.getvalue())
            self.assertIn("Python 1", text_output.getvalue())

            json_output = StringIO()
            with redirect_stdout(json_output):
                self.assertEqual(main(["scan", directory, "--format", "json"]), 0)
            report = json.loads(json_output.getvalue())
            self.assertEqual(report["schemaVersion"], 1)
            self.assertEqual(report["files"], [{"path": "main.py", "language": "Python"}])

    def test_out_writes_report(self):
        with tempfile.TemporaryDirectory(prefix="byakugan-cli-") as directory:
            root = Path(directory)
            (root / "main.go").write_text("package main\n", encoding="utf-8")
            output = root / "report.json"
            stdout = StringIO()
            with redirect_stdout(stdout):
                self.assertEqual(main(["scan", directory, "--format", "json", "--out", str(output)]), 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["summary"]["languages"], {"Go": 1})


if __name__ == "__main__":
    unittest.main()
