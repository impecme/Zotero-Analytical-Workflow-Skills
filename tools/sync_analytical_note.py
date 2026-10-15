"""Attach the authoritative Vault Markdown to its Zotero parent, idempotently.

Requires PyYAML and an already authorized Zotero Desktop local write API.
Credentials are read locally and are never included in output or receipts.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.request
import yaml

TAG = 'research-vault-analytical-note'


def metadata(path):
    text = path.read_text(encoding='utf-8-sig')
    parts = text.split('---', 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError('Missing YAML frontmatter')
    return yaml.safe_load(parts[1])


def synchronize(vault, note, get, post):
    vault, note = Path(vault).resolve(), Path(note).resolve()
    note.relative_to(vault / '02vault')
    if note.suffix.lower() != '.md':
        raise ValueError('Expected an Analytical Note Markdown file')
    fm = metadata(note)
    if fm.get('type') != 'literature-note' or not fm.get('zotero_key'):
        raise ValueError('Not a stable-identity Analytical Note')
    key = fm['zotero_key']
    full = (vault / fm['fulltext_path']).resolve()
    full.relative_to(vault / '03fulltext')
    ff = metadata(full)
    if ff.get('zotero_key') != key or ff.get('note_path') != note.relative_to(vault).as_posix():
        raise ValueError('Note/Fulltext identity or reverse link mismatch')
    parent = get('/items/' + key)
    if parent['data']['itemType'] in ('note', 'attachment'):
        raise ValueError('Parent must be a bibliographic item')
    children = get('/items/' + key + '/children')
    def matches(item):
        d = item['data']
        return d.get('itemType') == 'attachment' and (
            any(t.get('tag') == TAG for t in d.get('tags', [])) or
            (d.get('linkMode') == 'linked_file' and d.get('path') and Path(d['path']).resolve() == note))
    hits = [x for x in children if matches(x)]
    if len(hits) > 1:
        raise ValueError('Multiple analytical-note attachments: review without deleting any')
    desired = dict(title='ResearchVault 精读：' + str(fm.get('title', note.stem)),
                   path=str(note), contentType='text/markdown')
    action = 'unchanged'
    if hits:
        hit = hits[0]
        if hit['data'].get('parentItem') != key or hit['data'].get('linkMode') != 'linked_file':
            raise ValueError('Managed attachment has unexpected parent or link mode')
        tags = hit['data'].get('tags', [])
        if not any(t.get('tag') == TAG for t in tags):
            tags = tags + [{'tag': TAG}]
        if any(hit['data'].get(k) != v for k, v in desired.items()) or tags != hit['data'].get('tags', []):
            payload = dict(key=hit['key'], version=hit['version'], tags=tags, **desired)
            action = 'updated'
    else:
        payload = dict(itemType='attachment', parentItem=key, linkMode='linked_file',
                       tags=[{'tag': TAG}], **desired)
        action = 'created'
    if action != 'unchanged':
        result = post('/items', [payload])
        if result.get('failed'):
            raise RuntimeError('Zotero rejected attachment write; retry after resolving API error')
    # A failed/uncertain write is not retried blindly. Read-back also makes a later rerun safe.
    verified = [x for x in get('/items/' + key + '/children') if matches(x)]
    if len(verified) != 1:
        raise RuntimeError('Attachment read-back did not resolve uniquely')
    attachment = verified[0]
    if attachment['data'].get('parentItem') != key or any(attachment['data'].get(k) != v for k, v in desired.items()):
        raise RuntimeError('Attachment read-back mismatch')
    receipt = dict(status='ZOTERO_NOTE_SYNCED', action=action, zotero_key=key,
                   attachment_key=attachment['key'], note_path=note.relative_to(vault).as_posix(),
                   note_sha256=hashlib.sha256(note.read_bytes()).hexdigest(), mode='linked_file')
    destination = vault / '01knowledge/.meta/zotero-note-sync' / (key + '.json')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True)
    parser.add_argument('--note', required=True)
    parser.add_argument('--auth-file', default=str(Path.home() / '.codex/zotero-local-auth.json'))
    parser.add_argument('--keys-file', help='Zotero profile localAPIKeys.json; alternatively ZOTERO_API_KEY environment variable')
    parser.add_argument('--app-name-prefix', default='Codex：', help='Only use an already authorized matching application key')
    args = parser.parse_args()
    auth = json.loads(Path(args.auth_file).read_text(encoding='utf8'))
    token = os.environ.get('ZOTERO_API_KEY')
    if not token and args.keys_file:
        keys = json.loads(Path(args.keys_file).read_text(encoding='utf8')).get('keys', [])
        matching = [x for x in keys if x.get('appName', '').startswith(args.app_name_prefix)]
        if matching:
            token = matching[-1]['key']
    if not token:
        raise RuntimeError('ZOTERO_NOTE_SYNC_DEFERRED: existing write authorization unavailable')
    def request(path, payload=None):
        req = urllib.request.Request('http://127.0.0.1:23119/api/users/0' + path,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode(),
            headers={'Content-Type': 'application/json', 'Zotero-Server-ID': auth['server_id'], 'Zotero-API-Key': token},
            method='GET' if payload is None else 'POST')
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response)
    print(json.dumps(synchronize(args.vault, args.note, request, request), ensure_ascii=False))


if __name__ == '__main__':
    main()
