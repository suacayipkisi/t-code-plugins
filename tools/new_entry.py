#!/usr/bin/env python3
"""Writes plugins/<id>.json for a plugin at a commit: downloads it, hashes its folder and copies the
fields from its plugin.json, so the entry matches what check.py compares.

    tools/new_entry.py https://github.com/<owner>/<repo> <commit> [path] [--category <word> ...]

When plugins/<id>.json is already there, the commit is added to its "versions" (made from the old
pin when it has none) and the entry's own pin becomes the most compatible row: a commit that needs a
newer plugin API (tapi_1_1, ...) does not reach the t-codes that only read the pin. Categories and the
reviews of the rows already there are kept.

Run tools/build_index.py afterwards. "reviewed" is always false for the new commit.
"""
import argparse
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check  # noqa: E402
from tree_hash import tree_hash  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent


def entry_for(repository, commit, path, categories, download=None):
    pin = {"repository": repository, "commit": commit, "path": path}
    with tempfile.TemporaryDirectory() as tmp:
        folder = (download or check.download)(pin, tmp)
        manifest = json.loads((folder / "plugin.json").read_text())
        entry = {
            "id": manifest.get("id", folder.name),
            "name": manifest["name"],
            "provider": check.provider_of(manifest, repository),
            "description": manifest.get("description", ""),
            "version": manifest.get("version", ""),
            "api": manifest.get("api", ""),
            "repository": repository,
            "commit": commit,
            "path": path,
            "tree-sha256": tree_hash(folder),
            "permissions": sorted(manifest.get("permissions") or []),
            "categories": categories,
            "reviewed": False,
        }
        if manifest.get("requires"):
            entry["requires"] = manifest["requires"]
        return entry


def row_of(entry):
    """The entry's pin as a "versions" row (path, permissions and requires too: they may change)."""
    row = {key: entry[key] for key in check.PIN}
    for key in ("path", "permissions", "requires"):
        if key in entry:
            row[key] = entry[key]
    if entry.get("reviewed"):
        row["reviewed"] = True
    return row


def merged(old, new):
    """new (a fresh entry_for) added to old's versions, the pin the most compatible row."""
    rows = [r for r in old.get("versions") or [row_of(old)] if r["commit"] != new["commit"]] + [row_of(new)]
    pin = check.most_compatible(rows)
    entry = dict(new, categories=old.get("categories") or new["categories"])
    for key in check.PIN:
        entry[key] = pin[key]
    for key in ("path", "permissions", "requires"):
        entry.pop(key, None)
        if key in pin:
            entry[key] = pin[key]
    entry.setdefault("path", "")
    entry["reviewed"] = bool(pin.get("reviewed"))
    entry["versions"] = rows
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repository")
    parser.add_argument("commit")
    parser.add_argument("path", nargs="?", default="")
    parser.add_argument("--category", action="append", default=[])
    args = parser.parse_args()
    entry = entry_for(args.repository.rstrip("/"), args.commit, args.path.strip("/"), args.category)
    target = ROOT / "plugins" / f"{entry['id']}.json"
    if target.exists():
        entry = merged(json.loads(target.read_text()), entry)
    target.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {target.relative_to(ROOT)}: now run tools/build_index.py and tools/check.py {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
