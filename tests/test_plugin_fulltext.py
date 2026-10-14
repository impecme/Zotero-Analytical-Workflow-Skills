from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prepare_fulltext


class PluginFulltextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.data = self.base / "Zotero"
        self.pdf = self.data / "storage/PDFKEY01/paper.pdf"
        self.pdf.parent.mkdir(parents=True)
        self.pdf.write_bytes(b"original PDF bytes")
        os.utime(self.pdf, (1700000000, 1700000000))
        with contextlib.closing(sqlite3.connect(self.data / "zotero.sqlite")) as db:
            db.executescript("""
                CREATE TABLE items(itemID INTEGER PRIMARY KEY, key TEXT);
                CREATE TABLE itemAttachments(itemID INTEGER, parentItemID INTEGER, path TEXT, contentType TEXT);
                INSERT INTO items VALUES (1, 'PARENT01'), (2, 'PDFKEY01');
                INSERT INTO itemAttachments VALUES (2, 1, 'storage:paper.pdf', 'application/pdf');
            """)
        self.cache = self.data / "llm-for-zotero-mineru/2"
        (self.cache / "images").mkdir(parents=True)
        (self.cache / "images/figure.png").write_bytes(b"figure bytes")
        self.body = "# Paper\n\nOriginal findings.\n\n![Figure](images/figure.png)\n"
        (self.cache / "full.md").write_bytes(self.body.encode("utf-8"))
        self.provenance = {
            "kind": "llm-for-zotero/mineru-cache-source", "version": 2,
            "attachmentId": 2, "attachmentKey": "PDFKEY01", "parentItemKey": "PARENT01",
            "sourceFilename": "paper.pdf", "parsedAt": "2024-01-01T00:00:00Z",
        }
        self.write_provenance()
        self.manifest = {
            "sections": [{"heading": "Paper", "path": "Paper", "level": 1, "charStart": 0,
                          "charEnd": len(self.body), "figures": [{"path": "images/figure.png"}], "tables": []}],
            "totalChars": len(self.body), "totalPages": 1,
            "allFigures": [{"path": "images/figure.png"}], "allTables": [],
            "figureBlocks": [{"imagePaths": ["images/figure.png"]}], "structure": {"version": 2},
        }
        self.write_manifest()
        self.output = self.base / "staging"

    def write_manifest(self):
        (self.cache / "manifest.json").write_text(json.dumps(self.manifest))

    def write_provenance(self):
        (self.cache / "_llm_source.json").write_text(json.dumps(self.provenance))

    def argv(self):
        return ["prepare_fulltext", "--key", "PARENT01", "--data-dir", str(self.data), "--output", str(self.output)]

    def run_main(self, extra=()):
        with mock.patch.object(sys, "argv", self.argv() + list(extra)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return prepare_fulltext.main()

    def assert_fallback(self, expected_reason):
        with mock.patch.object(prepare_fulltext.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(self.run_main(), 7)
        command = run.call_args.args[0]
        self.assertEqual(Path(command[1]).name, "run_mineru_production.py")
        self.assertEqual(Path(command[command.index("--input") + 1]), self.pdf.resolve())
        self.assertFalse(self.output.exists())
        with self.assertRaises((prepare_fulltext.CacheRejected, OSError, ValueError)) as caught:
            prepare_fulltext.validate_cache(self.cache, prepare_fulltext.resolve_pdf(self.data, "PARENT01", None))
        self.assertIn(expected_reason, str(caught.exception))

    def test_cli_reuses_cache_without_mineru_and_keeps_source_unchanged(self):
        before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.data.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(ROOT / "tools/prepare_fulltext.py"), *self.argv()[1:]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PLUGIN_CACHE_REUSED")
        self.assertEqual((self.output / "raw/full.md").read_text(encoding="utf-8"), self.body)
        self.assertEqual((self.output / "raw/images/figure.png").read_bytes(), b"figure bytes")
        status = json.loads((self.output / "production-status.json").read_text())
        self.assertEqual(status["zotero_key"], "PARENT01")
        self.assertEqual(status["page_mapping"], "unknown")
        self.assertEqual(before, {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in self.data.rglob("*") if p.is_file()})

    def test_missing_cache_falls_back(self):
        (self.cache / "full.md").unlink()
        self.assert_fallback("full.md")

    def test_wrong_identity_falls_back(self):
        self.provenance["attachmentKey"] = "WRONG001"
        self.write_provenance()
        self.assert_fallback("identity")

    def test_pdf_newer_than_cache_falls_back(self):
        os.utime(self.pdf, (1800000000, 1800000000))
        self.assert_fallback("newer")

    def test_restore_time_does_not_replace_missing_parse_time(self):
        del self.provenance["parsedAt"]
        self.provenance["restoredAt"] = "2024-02-01T00:00:00Z"
        self.write_provenance()
        self.assert_fallback("original parse time")

    def test_pending_write_falls_back(self):
        (self.cache / "_llm_write_pending.json").write_text("{}")
        self.assert_fallback("pending")

    def test_missing_image_falls_back(self):
        (self.cache / "images/figure.png").unlink()
        self.assert_fallback("Missing")

    def test_manifest_only_image_is_checked(self):
        text = "Original findings without image embeds."
        (self.cache / "full.md").write_text(text)
        self.manifest["totalChars"] = len(text)
        self.write_manifest()
        (self.cache / "images/figure.png").unlink()
        self.assert_fallback("Missing")

    def test_path_escape_falls_back(self):
        (self.cache / "full.md").write_text("![Image](../../../storage/PDFKEY01/paper.pdf)")
        self.assert_fallback("escaping")

    def test_unsupported_reference_image_falls_back(self):
        (self.cache / "full.md").write_text("![Image][figure]\n[figure]: images/figure.png")
        self.assert_fallback("Unsupported Markdown")

    def test_invalid_provenance_falls_back(self):
        (self.cache / "_llm_source.json").write_text("[]")
        self.assert_fallback("provenance")

    def test_unknown_provenance_version_falls_back(self):
        self.provenance["version"] = 99
        self.write_provenance()
        self.assert_fallback("provenance")

    def test_truncated_markdown_falls_back(self):
        (self.cache / "full.md").write_text("Truncated.")
        self.assert_fallback("text length mismatch")

    def test_figure_block_image_is_checked(self):
        self.manifest["figureBlocks"] = [{"imagePaths": ["images/absent.png"]}]
        self.write_manifest()
        self.assert_fallback("Missing")

    def test_utf16_length_matches_javascript_with_unicode_and_crlf(self):
        text = self.body.replace("\n", "\r\n") + "\U0001f52c"
        (self.cache / "full.md").write_bytes(text.encode("utf-8"))
        self.manifest["totalChars"] = len(text) + 1
        self.write_manifest()
        self.assertEqual(self.run_main(), 0)
        self.assertEqual((self.output / "raw/full.md").read_bytes(), text.encode("utf-8"))

    def test_existing_output_is_never_overwritten(self):
        self.output.mkdir()
        (self.output / "keep.txt").write_text("keep")
        with self.assertRaises(SystemExit), mock.patch.object(prepare_fulltext.subprocess, "run") as run:
            self.run_main()
        run.assert_not_called()
        self.assertEqual((self.output / "keep.txt").read_text(), "keep")

    def test_multiple_attachments_require_explicit_pdf_key(self):
        with contextlib.closing(sqlite3.connect(self.data / "zotero.sqlite")) as db:
            db.executescript("INSERT INTO items VALUES (3, 'PDFKEY02'); INSERT INTO itemAttachments VALUES (3, 1, 'storage:other.pdf', 'application/pdf');")
        with self.assertRaises(SystemExit):
            self.run_main()
        self.assertEqual(self.run_main(["--pdf-key", "PDFKEY01"]), 0)

    def test_zotero_directory_cannot_be_used_as_staging(self):
        with self.assertRaises(SystemExit):
            self.run_main(["--output", str(self.data / "new-output")])
        self.assertFalse((self.data / "new-output").exists())

    def test_cache_change_during_copy_is_rejected(self):
        copy = prepare_fulltext.shutil.copyfile
        def changing_copy(source, dest):
            result = copy(source, dest)
            if Path(source).name == "full.md":
                (self.cache / "full.md").write_text("changed during snapshot")
            return result
        with mock.patch.object(prepare_fulltext.shutil, "copyfile", side_effect=changing_copy), mock.patch.object(prepare_fulltext.subprocess, "run", return_value=subprocess.CompletedProcess([], 2)) as run:
            self.assertEqual(self.run_main(), 2)
            run.assert_called_once()
        self.assertFalse(self.output.exists())
        self.assertEqual(list(self.base.glob(".cache-stage-*")), [])


if __name__ == "__main__":
    unittest.main()
