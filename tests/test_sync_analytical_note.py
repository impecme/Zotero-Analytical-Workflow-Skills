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
        if path.endswith('/children'):
            return [x for x in self.children if not x['data'].get('deleted')]
        return next((x for x in self.children if path.endswith('/' + x['key'])), {'data': {'itemType': 'journalArticle'}})

    def post(self, path, payload):
        self.writes += 1
        d = payload[0]
        if 'key' in d:
            target = next(x for x in self.children if x['key'] == d['key'])
            target['data'].update({k: v for k, v in d.items() if k not in ('key', 'version')})
            target['version'] += 1
        else:
            self.children.append({'key': 'NOTE' + str(len(self.children)), 'version': 1, 'data': d.copy()})
        return {'successful': {}, 'failed': {}}

    def test_repeated_run_and_body_edit_do_not_duplicate(self):
        first = sync.synchronize(self.v, self.note, self.get, self.post)
        self.note.write_text(self.note.read_text(encoding='utf8') + '\nUpdated', encoding='utf8')
        second = sync.synchronize(self.v, self.note, self.get, self.post)
        third = sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(self.writes, 2)
        self.assertEqual(first['note_key'], second['note_key'])
        self.assertEqual(third['action'], 'unchanged')
        self.assertEqual(len(self.children), 1)
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

    def test_manual_edits_are_preserved(self):
        sync.synchronize(self.v, self.note, self.get, self.post)
        self.children[0]['data']['note'] += '<p>Manual edit</p>'
        with self.assertRaisesRegex(ValueError, 'SYNC_CONFLICT'):
            sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(self.writes, 1)

    def test_tagged_link_retired_only_after_native_verified(self):
        legacy = {'key': 'OLDLINK', 'version': 1, 'data': dict(itemType='attachment', parentItem='ABCD1234',
            linkMode='linked_file', path=str(self.note), tags=[{'tag': sync.TAG}])}
        self.children.append(legacy)
        result = sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(result['retired_linked_files'], ['OLDLINK'])
        self.assertTrue(legacy['data']['deleted'])
        self.assertTrue(self.note.exists())
        self.assertEqual(len(self.get('/items/ABCD1234/children')), 1)

    def test_write_failure_preserves_legacy(self):
        legacy = {'key': 'OLDLINK', 'version': 1, 'data': dict(itemType='attachment', parentItem='ABCD1234',
            linkMode='linked_file', path=str(self.note), tags=[{'tag': sync.TAG}])}
        self.children.append(legacy)
        with self.assertRaises(RuntimeError):
            sync.synchronize(self.v, self.note, self.get, lambda p, d: {'failed': {'0': 'denied'}})
        self.assertFalse(legacy['data'].get('deleted'))

    def test_math_tables_links_and_code(self):
        with self.note.open('a', encoding='utf8') as f:
            f.write('\n\n| Value | Link |\n| --- | --- |\n| $x_1$ | [[02vault/n\\|中文别名]] |\n\n$$\n\\frac{x}{2} < 3\n$$\n\n`$not_math$` and `[[keep]]`\n')
        rendered, stats = sync.render_note(self.v, self.note)
        self.assertEqual(stats, dict(tables=1, math_inline=1, math_display=1))
        self.assertIn('<pre class="math">$$\\frac{x}{2} &lt; 3$$</pre>', rendered)
        self.assertIn('中文别名</a>', rendered)
        self.assertIn('<code>$not_math$</code>', rendered)
        self.assertIn('<code>[[keep]]</code>', rendered)
        self.assertIn('<table>', rendered)

    def test_image_not_silently_dropped(self):
        with self.note.open('a', encoding='utf8') as f:
            f.write('\n\n![figure](figure.png)')
        with self.assertRaisesRegex(ValueError, 'image import'):
            sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(self.writes, 0)

    def test_editor_serialization_does_not_look_like_manual_edits(self):
        before = '<div data-schema-version="9"><table><thead><tr><th>A</th></tr></thead><tbody><tr><td>B</td></tr></tbody></table><ul><li><p>C</p></li></ul><p><a href="obsidian://open">主稿</a></p></div>'
        after = '<div data-schema-version="8"><table><tbody><tr><th><p>A</p></th></tr><tr><td><p>B</p></td></tr></tbody></table><ul><li>C</li></ul><p><a rel="noopener noreferrer nofollow" href="obsidian://open">主稿</a></p></div>'
        self.assertEqual(sync.content_hash(before), sync.content_hash(after))
        self.assertNotEqual(sync.content_hash(before), sync.content_hash(after.replace('>B<', '>Changed<')))

    def test_unmanaged_notes_and_links_are_preserved(self):
        manual = {'key': 'MANUAL01', 'version': 1, 'data': dict(itemType='note', parentItem='ABCD1234', note='<p>My notes</p>', tags=[])}
        link = {'key': 'LINK0001', 'version': 1, 'data': dict(itemType='attachment', parentItem='ABCD1234', linkMode='linked_file', path=str(self.note), tags=[])}
        self.children.extend([manual, link])
        sync.synchronize(self.v, self.note, self.get, self.post)
        self.assertEqual(manual['data']['note'], '<p>My notes</p>')
        self.assertFalse(link['data'].get('deleted'))


if __name__ == '__main__':
    unittest.main()
