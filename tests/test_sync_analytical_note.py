import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('sync', Path(__file__).parents[1] / 'tools/sync_analytical_note.py')
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.v = Path(self.temp.name)
        (self.v / '02vault').mkdir()
        (self.v / '03fulltext').mkdir()
        self.note = self.v / '02vault/n.md'
        self.note.write_text('---\ntype: literature-note\nzotero_key: ABCD1234\ntitle: Test\nfulltext_path: 03fulltext/f.md\n---\nBody', encoding='utf8')
        (self.v / '03fulltext/f.md').write_text('---\nzotero_key: ABCD1234\nnote_path: 02vault/n.md\n---\nOriginal', encoding='utf8')
        self.children = []
        self.writes = 0

    def get(self, path):
        return self.children if path.endswith('/children') else {'data': {'itemType': 'journalArticle'}}

    def post(self, path, payload):
        self.writes += 1
        d = payload[0]
        self.children.append({'key': 'ATTACH01', 'version': 1, 'data': d.copy()})
        return {'successful': {'0': self.children[-1]}, 'failed': {}}

    def test_repeated_run_and_body_edit_do_not_duplicate(self):
        first = sync.synchronize(self.v, self.note, self.get, self.post)
        self.note.write_text(self.note.read_text(encoding='utf8') + '\nUpdated', encoding='utf8')
        second = sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(self.writes, 1)
        self.assertEqual(first['attachment_key'], second['attachment_key'])
        self.assertNotEqual(first['note_sha256'], second['note_sha256'])

    def test_identity_mismatch_stops_before_write(self):
        p = self.v / '03fulltext/f.md'
        p.write_text(p.read_text().replace('ABCD1234', 'OTHERKEY'))
        with self.assertRaises(ValueError):
            sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(self.writes, 0)

    def test_duplicate_managed_attachments_stop_without_deletion(self):
        sync.synchronize(self.v, self.note, self.get, self.post)
        self.children.append(self.children[0].copy())
        with self.assertRaises(ValueError):
            sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(self.writes, 1)
        self.assertEqual(len(self.children), 2)


if __name__ == '__main__':
    unittest.main()
