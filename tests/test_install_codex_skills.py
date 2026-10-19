from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from install_codex_skills import install


class InstallTests(unittest.TestCase):
    def test_install_binds_resources_and_preserves_custom_analysis(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / "skills with spaces"
            targets = install(destination)
            self.assertEqual(len(targets), 7)
            writer = (destination / "zotero-analytical-writer/SKILL.md").read_text(encoding="utf-8")
            self.assertIn("教学示例，非论文实验数据", writer)
            self.assertIn(ROOT.as_posix(), writer)
            schema = (destination / "research-vault-knowledge-maintainer/references/knowledge-schema.md").read_text(encoding="utf-8")
            self.assertIn((ROOT / "templates").as_posix(), schema)
            self.assertFalse((destination / "config.toml").exists())

    def test_existing_customization_prevents_all_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)
            custom = destination / "zotero-analytical-writer"
            custom.mkdir()
            (custom / "SKILL.md").write_text("personal customization", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                install(destination)
            self.assertEqual(list(destination.iterdir()), [custom])
            self.assertEqual((custom / "SKILL.md").read_text(), "personal customization")


if __name__ == "__main__":
    unittest.main()
