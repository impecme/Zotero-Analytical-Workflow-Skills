"""Install workflow Skills without overwriting existing customizations.

Keep this checkout at its final location: installed Skills reference its tools
and templates. No Vault, Zotero data, configuration or credentials are copied.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def install(destination: Path, root: Path = ROOT) -> list[Path]:
    root = root.resolve()
    destination = destination.expanduser().resolve()
    sources = sorted((root / "skills").glob("*/SKILL.md"))
    if not sources:
        raise ValueError("No workflow Skills found")
    targets = [destination / source.parent.name for source in sources]
    conflicts = [str(target) for target in targets if target.exists() or target.is_symlink()]
    if conflicts:
        raise FileExistsError("Existing Skills preserved; compare/back up before reinstalling: " + ", ".join(conflicts))
    if destination.is_relative_to(root):
        raise ValueError("Install outside the checkout to keep machine paths out of Git")
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in zip(sources, targets):
        shutil.copytree(source.parent, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # Resolve cross-Skill links into the checkout; local references stay local.
        for document in target.rglob("*.md"):
            text = document.read_text(encoding="utf-8")
            original = source.parent / document.relative_to(target)
            import re
            def resolve_link(match: re.Match[str]) -> str:
                relative = match.group(1)
                resolved = (original.parent / relative).resolve()
                if relative.startswith("../") and resolved.is_relative_to(root) and resolved.exists():
                    return "](" + resolved.as_posix() + ")"
                return match.group(0)
            text = re.sub(r"\]\(([^)]+)\)", resolve_link, text)
            document.write_text(text, encoding="utf-8", newline="\n")
        skill = target / "SKILL.md"
        with skill.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(
                "\n\n## Local installation resources\n\n"
                f"The bundled repository is installed at `{root.as_posix()}`. "
                "Resolve repository-level `tools/`, `templates/`, and `config.toml` against this directory. "
                "Run bundled Python helpers with this directory as the working directory, or use absolute script paths. "
                "Configure the research Vault only when its location has been selected by the user.\n"
            )
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser.add_argument("--skills-dir", type=Path, default=home / "skills")
    args = parser.parse_args()
    try:
        for target in install(args.skills_dir):
            print(f"Installed: {target.name}")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
