# Read-only Zotero identity fallback acceptance

## Problem and behavior

When Zotero holds an exclusive SQLite lock, `prepare_fulltext.py` previously
failed before resolving the requested attachment. The reproduction uses an
isolated SQLite database with `BEGIN EXCLUSIVE`; before this change it raised
`sqlite3.OperationalError: database is locked`.

Only SQLite BUSY/LOCKED errors now trigger a loopback GET-only API fallback.
Other database errors still fail. The fallback validates parent-key uniqueness
across visible libraries, attachment ownership, and a stored PDF path under the
configured data directory. It does not authorize writes or modify Zotero settings.

The staging entry point checks the configured Vault layout and stops conversion
when formal Fulltext for the parent key already exists. `EXISTING_FULLTEXT` is
not a declaration that Note/Fulltext/Knowledge validation has passed.

## Verification

Run from the repository root:

```text
python -m unittest discover -s tests -v
```

The installed implementation passed 44 tests with one skip out of 45 tests.
The skipped test requires a separate Retrieval checkout unavailable in this
environment. The same suite is rerun against the Git working copy before commit.

Covered scenarios:

- Exclusive SQLite lock: identity fallback and cache reuse succeed.
- Existing formal Fulltext: no staging, conversion, or overwrite.
- Missing PDF: fail without creating output or running conversion.
- Incorrect Vault parent directory: fail before identity lookup or writes.
- Unavailable API: fail closed rather than treating it as permission to convert.
- Wrong parent, attachment storage directory, or ambiguous cross-library key:
  reject identity.
- Read-only preflight and source-content hash preservation.

Live verification against Zotero 10.0.6 selected an already archived paper using
explicit parent/attachment keys. The resolver reported `local-api-get` and the
entry point returned `EXISTING_FULLTEXT`. SHA-256 snapshots before and after
matched for 2,495 files across the selected original attachment, plugin cache,
and ResearchVault. No conversion or formal ingest was performed. Private item
keys, paths, source documents, caches, and machine configuration are deliberately
excluded from this report and commit.

## Limits

- The API fallback conservatively rejects linked attachments outside configured
  Zotero storage, since this path cannot prove their data-directory binding.
- Layout validation rejects an incorrect parent directory, but cannot distinguish
  two valid Vaults; callers must retain the intended target configuration.
- Cache metadata supplies the numeric cache directory only after independent
  API identity verification; it is not a source-PDF hash attestation.
- Existing malformed Fulltext requires explicit repair planning; this command
  does not overwrite it automatically.

Reference: https://www.zotero.org/support/dev/web_api/v3/local_api
