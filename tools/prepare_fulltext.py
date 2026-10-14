#!/usr/bin/env python3
"""Stage a verified llm-for-zotero cache, otherwise use the original MinerU runner.

This prepares evidence only. The Fulltext Archiver still owns formal Vault writes.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from config import configured_path, load_config
from run_mineru_production import digest, timestamp
from zotero_readonly_fetch import discover_data_dir


class CacheRejected(ValueError):
    """A cache is not safe to reuse; conversion may still proceed."""


def resolve_pdf(data_dir: Path, key: str, pdf_key: str | None) -> dict:
    """Resolve identity using Zotero's real schema, never a directory/title guess."""
    database = data_dir / "zotero.sqlite"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only = ON")
        parents = db.execute("SELECT itemID FROM items WHERE key=?", (key,)).fetchall()
        if len(parents) != 1:
            raise ValueError("Parent key must identify exactly one Zotero item across libraries")
        rows = db.execute(
            "SELECT i.itemID, i.key, a.path FROM itemAttachments a "
            "JOIN items i ON i.itemID=a.itemID "
            "WHERE a.parentItemID=? AND a.contentType='application/pdf'",
            (parents[0]["itemID"],),
        ).fetchall()
    if pdf_key:
        rows = [r for r in rows if r["key"] == pdf_key]
    if len(rows) != 1:
        raise ValueError("Expected one PDF attachment; specify --pdf-key when there are multiple")
    row = rows[0]
    value = row["path"] or ""
    if value.startswith("storage:"):
        storage = (data_dir / "storage" / row["key"]).resolve()
        pdf = (storage / value.removeprefix("storage:")).resolve()
        if not pdf.is_relative_to(storage):
            raise ValueError("PDF storage path escapes its attachment directory")
    elif Path(value).is_absolute():
        pdf = Path(value).resolve()
    else:
        raise ValueError("Linked PDF path cannot be resolved; use Zotero API/export to locate it")
    if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
        raise ValueError("The selected PDF is not accessible")
    return {"zotero_key": key, "pdf_key": row["key"], "attachment_id": row["itemID"], "pdf": pdf}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def check_asset(root: Path, reference: str) -> None:
    parsed = urlsplit(reference)
    relative = unquote(parsed.path).replace("\\", "/")
    if parsed.scheme or parsed.netloc or not relative or ":" in relative:
        raise CacheRejected("Non-local or invalid image reference")
    asset = (root / relative).resolve()
    if not asset.is_relative_to(root.resolve()) or not asset.is_file() or not asset.stat().st_size:
        raise CacheRejected("Missing, empty or escaping image: " + reference)


def check_manifest_assets(root: Path, value) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ("path", "img_path") and isinstance(child, str) and child:
                check_asset(root, child)
            else:
                check_manifest_assets(root, child)
    elif isinstance(value, list):
        for child in value:
            check_manifest_assets(root, child)


def validate_cache(cache: Path, identity: dict) -> dict[str, str]:
    """Check a published cache and return a content fingerprint for snapshot checks.

    parsedAt vs PDF mtime is a conservative freshness heuristic, not proof that
    the plugin parsed identical PDF bytes. The plugin does not provide a PDF hash.
    """
    if not cache.is_dir():
        raise CacheRejected("Plugin cache missing")
    if (cache / "_llm_write_pending.json").exists():
        raise CacheRejected("Plugin cache write is pending")
    if cache.is_symlink() or cache.resolve() != cache.absolute():
        raise CacheRejected("Linked cache directory is not supported")
    files = {}
    for path in cache.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(cache.resolve()):
            raise CacheRejected("Cache contains a link or escaping path")
        if path.is_file():
            files[path.relative_to(cache).as_posix()] = digest(path)
    provenance = read_json(cache / "_llm_source.json")
    if not isinstance(provenance, dict) or provenance.get("kind") != "llm-for-zotero/mineru-cache-source" or provenance.get("version") != 1:
        raise CacheRejected("Unsupported plugin provenance")
    expected = {"attachmentId": identity["attachment_id"], "attachmentKey": identity["pdf_key"], "parentItemKey": identity["zotero_key"]}
    if any(provenance.get(k) != v for k, v in expected.items()):
        raise CacheRejected("Plugin cache identity does not match selected Zotero PDF")
    if provenance.get("sourceFilename") != identity["pdf"].name:
        raise CacheRejected("Plugin cache source filename does not match PDF")
    parsed_at = provenance.get("parsedAt")
    if not isinstance(parsed_at, str):
        raise CacheRejected("Cache has no original parse time (restored time is insufficient)")
    parsed = datetime.fromisoformat(parsed_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.timestamp() > datetime.now(timezone.utc).timestamp() + 300:
        raise CacheRejected("Invalid cache parse time")
    if identity["pdf"].stat().st_mtime > parsed.timestamp():
        raise CacheRejected("PDF is newer than plugin cache")
    markdown = (cache / "full.md").read_text(encoding="utf-8-sig")
    if not markdown.strip():
        raise CacheRejected("Plugin Markdown is empty")
    # Unsupported image syntax must fall back, never silently lose images.
    inline = re.compile(r'!\[[^\]\n]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+"[^"\n]*")?\s*\)')
    images = list(inline.finditer(markdown))
    if len(images) != markdown.count("![") or "![[" in markdown:
        raise CacheRejected("Unsupported Markdown image syntax; use original conversion")
    for match in images:
        check_asset(cache, match.group(1) or match.group(2))
    for tag in re.findall(r"<img\b[^>]*>", markdown, re.I):
        source = re.search(r'''\bsrc\s*=\s*["']([^"']+)["']''', tag, re.I)
        if not source:
            raise CacheRejected("Unsupported HTML image syntax")
        check_asset(cache, source.group(1))
    manifest = read_json(cache / "manifest.json")
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sections"), list):
        raise CacheRejected("Missing or unsupported plugin manifest")
    check_manifest_assets(cache, manifest)
    if (cache / "content_list.json").is_file():
        check_manifest_assets(cache, read_json(cache / "content_list.json"))
    return files


def stage_cache(cache: Path, identity: dict, output: Path) -> None:
    before_pdf = digest(identity["pdf"])
    files = validate_cache(cache, identity)
    # Prepare a private sibling; publish only a complete, unchanged snapshot.
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.parent / (".cache-stage-" + uuid4().hex)
    try:
        raw = temporary / "raw"
        raw.mkdir(parents=True)
        for relative in files:
            destination = raw / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cache / relative, destination)
        if validate_cache(cache, identity) != files or validate_cache(raw, identity) != files or digest(identity["pdf"]) != before_pdf:
            raise CacheRejected("Cache or PDF changed during snapshot; retry or convert")
        status = {
            "finished_at": timestamp(), "final_status": "PLUGIN_CACHE_REUSED",
            "source_type": "llm-for-zotero", "source_cache": str(cache),
            "zotero_key": identity["zotero_key"], "pdf_key": identity["pdf_key"],
            "source_pdf": str(identity["pdf"]), "sha256": before_pdf,
            "source_read_only": True, "output_markdown_files": 1,
            "freshness_check": "parsedAt >= PDF mtime; not a source-PDF hash attestation",
            "page_mapping": "unknown", "cache_files_sha256": files,
        }
        (temporary / "production-status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        # An existing output is always an error, including a concurrent creator.
        output.mkdir()
        for child in temporary.iterdir():
            shutil.move(str(child), str(output / child.name))
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key", required=True, help="Zotero parent item key")
    parser.add_argument("--pdf-key", help="required if the parent has several PDFs")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path, help="new staging directory, never a formal Fulltext path")
    parser.add_argument("--mineru", type=Path)
    parser.add_argument("--method", choices=("auto", "txt", "ocr"), default="auto")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    settings = load_config(args.config)
    data = args.data_dir or configured_path("zotero_data_dir", settings) or discover_data_dir()
    if data is None:
        parser.error("Zotero data directory not found; set --data-dir")
    try:
        identity = resolve_pdf(data.expanduser().resolve(), args.key, args.pdf_key)
    except (OSError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    archive = configured_path("archive_root", settings)
    output = args.output or (archive / f"{identity['pdf_key']}-{uuid4().hex[:12]}" if archive else None)
    if output is None:
        parser.error("pass --output or configure archive_root")
    output = output.expanduser().resolve()
    if output.is_relative_to(data.expanduser().resolve()):
        parser.error("staging output must be outside the Zotero data directory")
    if output.exists():
        parser.error("output already exists; refusing to overwrite")
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    cache = data.expanduser().resolve() / "llm-for-zotero-mineru" / str(identity["attachment_id"])
    try:
        stage_cache(cache, identity, output)
    except (OSError, ValueError) as exc:
        if output.exists():
            parser.error(f"Staging failed after output creation; inspect output before retry: {exc}")
        reason = str(exc)
        print("Plugin cache not reused: " + reason, file=sys.stderr)
        command = [sys.executable, str(Path(__file__).with_name("run_mineru_production.py")), "--input", str(identity["pdf"]), "--output", str(output), "--method", args.method, "--timeout", str(args.timeout)]
        for name in ("config", "mineru"):
            if value := getattr(args, name):
                command.extend(["--" + name, str(value)])
        result = subprocess.run(command, check=False)
        status_file = output / "production-status.json"
        if status_file.is_file():
            status = read_json(status_file)
            status.update({"plugin_cache_rejection": reason, "zotero_key": identity["zotero_key"], "pdf_key": identity["pdf_key"]})
            status_file.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return result.returncode
    print(json.dumps({"output": str(output), "status": "PLUGIN_CACHE_REUSED", "markdown_files": 1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
