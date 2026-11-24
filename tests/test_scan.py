"""Behavior tests for the first, language-neutral project inventory."""

import json
from pathlib import Path
import tempfile
import unittest

from byakugan.scan import scan_project


class ScanProjectTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="byakugan-test-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write(self, relative_path, content):
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def test_mixed_project_reports_languages_and_framework_evidence(self):
        self.write("backend/requirements.txt", "Django>=4.2\n")
        self.write("backend/models.py", "class Book:\n    pass\n")
        self.write("frontend/package.json", json.dumps({"dependencies": {"react": "18"}}))
        self.write("frontend/App.tsx", "export function App() { return null; }\n")
        self.write("server/package.json", json.dumps({"dependencies": {"express": "4"}}))
        self.write("server/index.js", "const app = require('express')();\n")
        self.write("java/pom.xml", "<artifactId>spring-boot-starter-web</artifactId>\n")
        self.write("java/Book.java", "class Book {}\n")
        self.write("go/go.mod", "module example.com/book\nrequire github.com/gin-gonic/gin v1.10.0\n")
        self.write("go/main.go", "package main\n")
        self.write("node_modules/ignored.js", "console.log('ignored');\n")
        self.write(".venv/ignored.py", "print('ignored')\n")
        self.write(".git/ignored.java", "class Ignored {}\n")
        self.write("dist/bundle.js", "console.log('ignored');\n")

        report = scan_project(self.root)
        self.assertEqual(report, scan_project(self.root))
        self.assertEqual(report["schemaVersion"], 1)
        self.assertEqual(report["project"]["name"], self.root.name)
        self.assertEqual(report["summary"]["sourceFiles"], 5)
        self.assertEqual(
            report["summary"]["languages"],
            {"Go": 1, "Java": 1, "JavaScript": 1, "Python": 1, "TypeScript": 1},
        )
        self.assertEqual(
            {framework["name"] for framework in report["summary"]["frameworks"]},
            {"Django", "React", "Express", "Spring Boot", "Gin"},
        )
        for framework in report["summary"]["frameworks"]:
            self.assertTrue(framework["evidence"])

        paths = [file["path"] for file in report["files"]]
        self.assertEqual(paths, sorted(paths))
        self.assertEqual(
            set(paths),
            {"backend/models.py", "frontend/App.tsx", "server/index.js", "java/Book.java", "go/main.go"},
        )
        self.assertEqual(report["warnings"], [])

    def test_missing_or_nondirectory_target_is_rejected(self):
        with self.assertRaises(ValueError):
            scan_project(self.root / "missing")
        self.write("file.py", "pass\n")
        with self.assertRaises(ValueError):
            scan_project(self.root / "file.py")

    def test_oversized_and_binary_source_files_are_skipped_with_warnings(self):
        self.write("small.py", "pass\n")
        (self.root / "binary.py").write_bytes(b"\x00\x01\x02")
        (self.root / "huge.py").write_bytes(b"x" * (512 * 1024 + 1))

        report = scan_project(self.root)
        self.assertEqual([file["path"] for file in report["files"]], ["small.py"])
        self.assertEqual(report["summary"]["sourceFiles"], 1)
        self.assertTrue(any("binary.py" in warning for warning in report["warnings"]))
        self.assertTrue(any("huge.py" in warning for warning in report["warnings"]))


if __name__ == "__main__":
    unittest.main()
