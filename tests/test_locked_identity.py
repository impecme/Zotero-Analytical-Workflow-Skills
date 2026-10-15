import contextlib
import sqlite3
import hashlib
import unittest
from unittest import mock

import test_plugin_fulltext
import prepare_fulltext
import zotero_identity_api


class LockedIdentityTests(unittest.TestCase):
    setUp = test_plugin_fulltext.PluginFulltextTests.setUp
    write_manifest = test_plugin_fulltext.PluginFulltextTests.write_manifest
    write_provenance = test_plugin_fulltext.PluginFulltextTests.write_provenance
    argv = test_plugin_fulltext.PluginFulltextTests.argv
    run_main = test_plugin_fulltext.PluginFulltextTests.run_main

    def test_locked_database_uses_readonly_api(self):
        identity = {"zotero_key": "PARENT01", "pdf_key": "PDFKEY01",
                    "attachment_id": 2, "pdf": self.pdf.resolve()}
        with contextlib.closing(sqlite3.connect(self.data / "zotero.sqlite")) as lock:
            lock.execute("BEGIN EXCLUSIVE")
            with mock.patch.object(prepare_fulltext, "resolve_pdf_api", return_value=identity, create=True) as api:
                self.assertEqual(prepare_fulltext.resolve_pdf(self.data, "PARENT01", None), identity)
                api.assert_called_once()

    def routes(self):
        parent = {"key": "PARENT01", "version": 1, "library": {"type": "user", "id": 1},
                  "data": {"key": "PARENT01", "itemType": "journalArticle"}}
        child = {"key": "PDFKEY01", "version": 1, "library": parent["library"],
                 "data": {"parentItem": "PARENT01", "itemType": "attachment", "contentType": "application/pdf", "linkMode": "imported_file"}}
        return {"/users/0/groups": [], "/users/0/items/PARENT01": parent,
                "/users/0/items/PARENT01/children": [child], "/users/0/items/PDFKEY01": child,
                "/users/0/items/PDFKEY01/file/view/url": self.pdf.as_uri()}

    def api(self, routes):
        return mock.patch.object(zotero_identity_api.LocalAPI, "get", side_effect=lambda path, **kw: routes[path])

    def hashes(self):
        return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for root in (self.data, self.vault)
                for p in root.rglob("*") if p.is_file()}

    def test_locked_cli_reuses_cache_readonly(self):
        before = self.hashes()
        with contextlib.closing(sqlite3.connect(self.data / "zotero.sqlite")) as lock:
            lock.execute("BEGIN EXCLUSIVE")
            with self.api(self.routes()), mock.patch.object(prepare_fulltext.subprocess, "run") as mineru:
                self.assertEqual(self.run_main(), 0)
                mineru.assert_not_called()
        self.assertEqual(before, self.hashes())
        self.assertTrue((self.output / "raw/full.md").exists())

    def test_existing_formal_fulltext_never_reprocessed(self):
        (self.vault / "03fulltext/PARENT01.md").write_text("existing formal evidence")
        before = self.hashes()
        with mock.patch.object(prepare_fulltext, "stage_cache") as stage, mock.patch.object(prepare_fulltext.subprocess, "run") as mineru:
            self.assertEqual(self.run_main(), 0)
            stage.assert_not_called()
            mineru.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.hashes())

    def test_missing_pdf_does_not_stage_or_convert(self):
        self.pdf.unlink()
        before = self.hashes()
        with self.assertRaises(SystemExit), mock.patch.object(prepare_fulltext.subprocess, "run") as mineru:
            self.run_main()
        mineru.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.hashes())

    def test_wrong_vault_stops_before_identity_or_write(self):
        self.config.write_text('[paths]\nvault_root = "' + self.base.as_posix() + '"\n')
        before = self.hashes()
        with self.assertRaises(SystemExit), mock.patch.object(prepare_fulltext, "resolve_pdf") as identity:
            self.run_main()
        identity.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.hashes())

    def test_api_rejects_wrong_parent_and_wrong_data_directory(self):
        for mutation in ("parent", "path", "multiple"):
            routes = self.routes()
            if mutation == "parent":
                routes["/users/0/items/PDFKEY01"]["data"]["parentItem"] = "WRONG001"
            elif mutation == "path":
                routes["/users/0/items/PDFKEY01/file/view/url"] = (self.base / "other.pdf").as_uri()
            else:
                routes["/users/0/items/PARENT01/children"] *= 2
            with self.subTest(mutation=mutation), self.api(routes), self.assertRaises(ValueError):
                zotero_identity_api.resolve_pdf_api(self.data, "PARENT01", None)

    def test_non_lock_sqlite_error_does_not_fallback(self):
        with mock.patch.object(prepare_fulltext, "resolve_pdf_sqlite", side_effect=sqlite3.OperationalError("no such table")), mock.patch.object(prepare_fulltext, "resolve_pdf_api") as api:
            with self.assertRaises(sqlite3.OperationalError):
                prepare_fulltext.resolve_pdf(self.data, "PARENT01", None)
            api.assert_not_called()

    def test_check_only_never_stages(self):
        before = self.hashes()
        self.assertEqual(self.run_main(["--check-only"]), 0)
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.hashes())

    def test_formal_vault_cannot_be_staging(self):
        with self.assertRaises(SystemExit):
            self.run_main(["--output", str(self.vault / "new-staging")])
        self.assertFalse((self.vault / "new-staging").exists())

    def test_locked_api_failure_is_not_conversion_permission(self):
        before = self.hashes()
        with contextlib.closing(sqlite3.connect(self.data / "zotero.sqlite")) as lock:
            lock.execute("BEGIN EXCLUSIVE")
            with mock.patch.object(prepare_fulltext, "resolve_pdf_api", side_effect=ValueError("API unavailable")), mock.patch.object(prepare_fulltext.subprocess, "run") as mineru:
                with self.assertRaises(SystemExit):
                    self.run_main()
                mineru.assert_not_called()
        self.assertFalse(self.output.exists())
        self.assertEqual(before, self.hashes())

    def test_api_missing_pdf_is_rejected(self):
        routes = self.routes()
        self.pdf.unlink()
        with self.api(routes), self.assertRaisesRegex(ValueError, "not accessible"):
            zotero_identity_api.resolve_pdf_api(self.data, "PARENT01", None)

    def test_same_key_in_two_libraries_is_rejected(self):
        routes = self.routes()
        routes["/users/0/groups"] = [{"id": 123}]
        routes["/groups/123/items/PARENT01"] = routes["/users/0/items/PARENT01"]
        with self.api(routes), self.assertRaisesRegex(ValueError, "exactly one"):
            zotero_identity_api.resolve_pdf_api(self.data, "PARENT01", None)
