"""GET-only loopback identity fallback. Never opens a writable Zotero database."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, url2pathname


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Zotero identity API must not redirect")


class LocalAPI:
    def __init__(self):
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.server_id = None

    def get(self, path, *, text=False):
        headers = {"Zotero-API-Version": "3"}
        if self.server_id:
            headers["Zotero-Server-ID"] = self.server_id
        request = Request("http://127.0.0.1:23119/api" + path, headers=headers, method="GET")
        try:
            with self.opener.open(request, timeout=5) as response:
                server = response.headers.get("Zotero-Server-ID")
                if self.server_id and server != self.server_id:
                    raise ValueError("Zotero instance changed during identity verification")
                self.server_id = server
                if response.headers.get("Link") and 'rel="next"' in response.headers["Link"]:
                    raise ValueError("Incomplete paginated Zotero identity response")
                body = response.read().decode("utf-8")
        except HTTPError:
            raise
        except (URLError, TimeoutError, OSError) as exc:
            raise ValueError("Zotero is locked and its local read API is unavailable; no files written") from exc
        return body.strip() if text else json.loads(body)


def resolve_pdf_api(data_dir: Path, key: str, pdf_key: str | None) -> dict:
    api = LocalAPI()
    try:
        groups = api.get("/users/0/groups")
        prefixes = ["/users/0"]
        for group in groups:
            group_id = group.get("id", group.get("data", {}).get("id"))
            if not isinstance(group_id, int) or group_id <= 0:
                raise ValueError("Invalid Zotero group identity")
            prefixes.append(f"/groups/{group_id}")
        matches = []
        for prefix in prefixes:
            try:
                parent = api.get(f"{prefix}/items/{key}")
            except HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            if parent.get("key") != key or parent.get("data", {}).get("deleted"):
                raise ValueError("Invalid or deleted Zotero parent identity")
            if parent["data"].get("itemType") in ("attachment", "note", "annotation"):
                raise ValueError("Expected a bibliographic parent item")
            matches.append((prefix, parent))
        if len(matches) != 1:
            raise ValueError("Parent key must identify exactly one Zotero item across libraries")
        prefix, parent = matches[0]
        children = api.get(f"{prefix}/items/{key}/children")
        rows = [item for item in children if item.get("data", {}).get("itemType") == "attachment"
                and item["data"].get("contentType") == "application/pdf"
                and not item["data"].get("deleted")]
        if pdf_key:
            rows = [item for item in rows if item.get("key") == pdf_key]
        if len(rows) != 1:
            raise ValueError("Expected one PDF attachment; specify --pdf-key when there are multiple")
        selected = rows[0]
        attachment = selected["key"]
        import re
        if not re.fullmatch(r"[A-Z0-9]{8}", attachment):
            raise ValueError("Invalid attachment key")
        if selected["data"].get("parentItem") != key or selected.get("library") != parent.get("library"):
            raise ValueError("Zotero attachment parent/library mismatch")
        value = api.get(f"{prefix}/items/{attachment}/file/view/url", text=True)
        parsed = urlsplit(value)
        if parsed.scheme != "file" or parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
            raise ValueError("Expected a local attachment file URL")
        pdf = Path(url2pathname(parsed.path)).resolve()
        # Stored PDFs bind the running API instance to the configured data directory.
        # Linked-file identity cannot establish that binding here; fail closed.
        storage = (data_dir / "storage" / attachment).resolve()
        if selected["data"].get("linkMode") not in ("imported_file", "imported_url") or not pdf.is_relative_to(storage):
            raise ValueError("API attachment is outside configured Zotero storage; verify data directory or resolve linked PDF explicitly")
        if not pdf.is_file() or pdf.suffix.lower() != ".pdf":
            raise ValueError("The selected PDF is not accessible")
        if api.get(f"{prefix}/items/{key}") != parent or api.get(f"{prefix}/items/{attachment}") != selected:
            raise ValueError("Zotero identity changed during verification; retry")
    except HTTPError as exc:
        raise ValueError(f"Zotero identity API returned HTTP {exc.code}; no files written") from exc

    # Numeric IDs are not exposed by the API. Locate cache metadata by verified
    # keys only; metadata never establishes parent/PDF identity on its own.
    ids = []
    for source in (data_dir / "llm-for-zotero-mineru").glob("*/_llm_source.json"):
        try:
            provenance = json.loads(source.read_text(encoding="utf-8-sig"))
            numeric = provenance.get("attachmentId")
            if (provenance.get("parentItemKey") == key and provenance.get("attachmentKey") == attachment
                    and type(numeric) is int and numeric > 0 and source.parent.name == str(numeric)):
                ids.append(numeric)
        except (OSError, ValueError, AttributeError):
            continue
    return {"zotero_key": key, "pdf_key": attachment, "attachment_id": ids[0] if len(ids) == 1 else None,
            "pdf": pdf, "identity_source": "local-api-get"}
