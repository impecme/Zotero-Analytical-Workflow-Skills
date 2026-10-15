"""Publish authoritative Vault Markdown as a native Zotero child note.

Requires PyYAML, markdown-it-py, mdit-py-plugins and an authorized local API.
Credentials are read locally and are never included in output or receipts.
"""
import argparse
import hashlib
import json
import os
import re
import html
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, unquote, urlparse
import urllib.request
import yaml

TAG = 'research-vault-analytical-note'


def obsidian_url(vault, relative):
    return 'obsidian://open?vault=' + quote(vault.name, safe='') + '&file=' + quote(relative, safe='')


def render_note(vault, note):
    """Use Zotero's own serialized math nodes, not pre-rendered KaTeX markup."""
    from markdown_it import MarkdownIt
    from mdit_py_plugins.dollarmath import dollarmath_plugin
    fm = metadata(note)
    body = note.read_text(encoding='utf-8-sig').split('---', 2)[2].lstrip()
    def wikilink(match):
        target, _, label = match.group(1).replace('\\|', '|').partition('|')
        return '[' + (label or target).replace('[', '\\[').replace(']', '\\]') + '](' + obsidian_url(vault, target) + ')'
    # Code is protected by the Markdown tokenizer: transform only inline text tokens.
    md = MarkdownIt('commonmark', {'html': False}).enable(['table', 'strikethrough'])
    md.use(dollarmath_plugin, allow_labels=False, allow_space=False, allow_digits=False)
    math = {'inline': 0, 'display': 0}
    def inline_math(tokens, idx, options, env):
        math['inline'] += 1
        return '<span class="math">$' + html.escape(tokens[idx].content) + '$</span>'
    def display_math(tokens, idx, options, env):
        math['display'] += 1
        return '<pre class="math">$$' + html.escape(tokens[idx].content.strip()) + '$$</pre>\n'
    md.renderer.rules['math_inline'] = inline_math
    md.renderer.rules['math_block'] = display_math
    # Wikilinks must be converted before table splitting because their aliases use pipes.
    # Protect fenced and inline code from this narrow source rewrite.
    protected = {}
    def protect(m):
        token = 'RVPROTECTEDCODE' + str(len(protected)) + 'TOKEN'
        protected[token] = m[0]
        return token
    body = re.sub(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*(?:\n|$)|`+[^`\n]*`+', protect, body)
    body = re.sub(r'(?<!!)\[\[([^\]\n]+)\]\]', wikilink, body)
    for token, value in protected.items():
        body = body.replace(token, value)
    tokens = md.parse(body)
    tables = sum(t.type == 'table_open' for t in tokens)
    for token in tokens:
        for child in token.children or []:
            if child.type == 'image':
                raise ValueError('Native image import is not implemented; keep source and defer instead of dropping images')
            if child.type == 'link_open':
                href = child.attrGet('href') or ''
                parsed = urlparse(href)
                if not parsed.scheme and href.lower().split('#')[0].endswith('.md'):
                    target = (note.parent / unquote(href.split('#')[0])).resolve()
                    child.attrSet('href', obsidian_url(vault, target.relative_to(vault).as_posix()))
    if re.search(r'!\[\[', body):
        raise ValueError('Embedded Obsidian files require native attachment import; sync deferred')
    rendered = md.renderer.render(tokens, md.options, {})
    source = html.escape(obsidian_url(vault, note.relative_to(vault).as_posix()), quote=True)
    title = html.escape(str(fm.get('title', note.stem)))
    result = ('<div data-schema-version="9"><h1>ResearchVault 精读：' + title + '</h1>'
              '<p><a href="' + source + '">在 Obsidian 中打开主稿</a></p>'
              '<p>本笔记从 Obsidian 单向同步。请在主稿编辑；Zotero 内的修改会触发同步冲突检查。</p>'
              + rendered + '</div>')
    return result, dict(tables=tables, math_inline=math['inline'], math_display=math['display'])


def content_hash(value):
    """Ignore serializer whitespace/attribute ordering, preserve all text and math."""
    class Canonical(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.parts = []
            self.cell_depth = 0
            self.list_depth = 0
        def handle_starttag(self, tag, attrs):
            if tag in ('td', 'th'):
                self.cell_depth += 1
            if tag == 'li':
                self.list_depth += 1
            if tag in ('thead', 'tbody', 'tfoot') or (tag == 'p' and (self.cell_depth or self.list_depth)):
                return
            attrs = [(k, v) for k, v in attrs if k not in ('rel', 'data-schema-version')]
            self.parts.append(('start', tag, sorted(attrs)))
        def handle_endtag(self, tag):
            if tag in ('thead', 'tbody', 'tfoot', 'br', 'hr', 'img') or (tag == 'p' and (self.cell_depth or self.list_depth)):
                return
            if tag in ('td', 'th'):
                self.cell_depth -= 1
            if tag == 'li':
                self.list_depth -= 1
            self.parts.append(('end', tag))
        def handle_data(self, data):
            if data.strip():
                self.parts.append(('text', data.strip()))
    parser = Canonical()
    parser.feed(value)
    return hashlib.sha256(json.dumps(parser.parts, ensure_ascii=False).encode()).hexdigest()


def metadata(path):
    text = path.read_text(encoding='utf-8-sig')
    parts = text.split('---', 2)
    if len(parts) != 3 or parts[0].strip():
        raise ValueError('Missing YAML frontmatter')
    return yaml.safe_load(parts[1])


def synchronize(vault, note, get, post, *, keep_linked_files=False, overwrite_managed_note=False):
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
    if (ff.get('zotero_key') != key or ff.get('note_path') != note.relative_to(vault).as_posix()
            or ff.get('pdf_key') != fm.get('pdf_key')):
        raise ValueError('Note/Fulltext identity or reverse link mismatch')
    parent = get('/items/' + key)
    if parent['data']['itemType'] in ('note', 'attachment'):
        raise ValueError('Parent must be a bibliographic item')
    desired_html, rendering = render_note(vault, note)
    destination = vault / '01knowledge/.meta/zotero-note-sync' / (key + '.json')
    prior = json.loads(destination.read_text(encoding='utf8')) if destination.exists() else {}
    children = get('/items/' + key + '/children')
    def matches(item):
        d = item['data']
        return not d.get('deleted') and d.get('itemType') == 'note' and (
            any(t.get('tag') == TAG for t in d.get('tags', [])) or
            item['key'] == prior.get('note_key'))
    hits = [x for x in children if matches(x)]
    if len(hits) > 1:
        raise ValueError('Multiple managed native notes: review without deleting any')
    desired = dict(note=desired_html)
    action = 'unchanged'
    if hits:
        hit = hits[0]
        if hit['data'].get('parentItem') != key:
            raise ValueError('Managed native note has unexpected parent')
        current_hash = content_hash(hit['data'].get('note', ''))
        desired_hash = content_hash(desired_html)
        if current_hash != desired_hash and current_hash != prior.get('native_note_hash') and not overwrite_managed_note:
            raise ValueError('ZOTERO_NOTE_SYNC_CONFLICT: managed note changed in Zotero or lacks a trusted receipt; preserve edits')
        tags = hit['data'].get('tags', [])
        if not any(t.get('tag') == TAG for t in tags):
            tags = tags + [{'tag': TAG}]
        if current_hash != desired_hash or tags != hit['data'].get('tags', []):
            payload = dict(key=hit['key'], version=hit['version'], tags=tags, **desired)
            action = 'updated'
    else:
        payload = dict(itemType='note', parentItem=key,
                       tags=[{'tag': TAG}], **desired)
        action = 'created'
    if action != 'unchanged':
        if hits:
            backup = destination.parent / 'backups' / (key + '-' + str(hits[0]['version']) + '.json')
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_text(json.dumps(hits[0], ensure_ascii=False, indent=2), encoding='utf8')
        result = post('/items', [payload])
        if result.get('failed'):
            raise RuntimeError('Zotero rejected native note write; retry after resolving API error')
    # A failed/uncertain write is not retried blindly. Read-back also makes a later rerun safe.
    verified = [x for x in get('/items/' + key + '/children') if matches(x)]
    if len(verified) != 1:
        raise RuntimeError('Native note read-back did not resolve uniquely')
    native = verified[0]
    if native['data'].get('parentItem') != key or content_hash(native['data'].get('note', '')) != content_hash(desired_html):
        raise RuntimeError('Native note read-back mismatch')
    receipt = dict(status='ZOTERO_NOTE_SYNCED', action=action, zotero_key=key,
                   note_key=native['key'], note_path=note.relative_to(vault).as_posix(),
                   note_sha256=hashlib.sha256(note.read_bytes()).hexdigest(), mode='native_note',
                   native_note_hash=content_hash(native['data']['note']), rendering=rendering,
                   retired_linked_files=[])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
    # Retire only our tagged links to this exact source, after successful native read-back.
    # Soft deletion affects the Zotero record, never the linked Markdown on disk.
    if not keep_linked_files:
        for old in children:
            d = old['data']
            if (not d.get('deleted') and d.get('parentItem') == key and d.get('itemType') == 'attachment'
                    and d.get('linkMode') == 'linked_file' and d.get('path')
                    and Path(d['path']).resolve() == note
                    and any(t.get('tag') == TAG for t in d.get('tags', []))):
                backup = destination.parent / 'backups' / (old['key'] + '-linked-file.json')
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    backup.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding='utf8')
                result = post('/items', [dict(key=old['key'], version=old['version'], deleted=1)])
                if result.get('failed'):
                    raise RuntimeError('Native note saved, legacy link retirement failed; rerun only sync')
                if not get('/items/' + old['key'])['data'].get('deleted'):
                    raise RuntimeError('Legacy link retirement read-back failed')
                receipt['retired_linked_files'].append(old['key'])
    destination.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding='utf8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', required=True)
    parser.add_argument('--note', required=True)
    parser.add_argument('--keep-linked-files', action='store_true')
    parser.add_argument('--overwrite-managed-note', action='store_true', help='Explicitly replace conflicting generated-note edits after saving a backup')
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
    print(json.dumps(synchronize(args.vault, args.note, request, request,
        keep_linked_files=args.keep_linked_files, overwrite_managed_note=args.overwrite_managed_note), ensure_ascii=False))


if __name__ == '__main__':
    main()
