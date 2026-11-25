#!/usr/bin/env python3
"""Writes plugins/<id>.json for a plugin at a commit: downloads it, hashes its folder and copies the
fields from its plugin.json, so the entry matches what check.py compares.

    tools/new_entry.py https://github.com/<owner>/<repo> <commit> [path] [--category <word> ...]

Run tools/build_index.py afterwards. "reviewed" is always false here.
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("repository")
    parser.add_argument("commit")
    parser.add_argument("path", nargs="?", default="")
    parser.add_argument("--category", action="append", default=[])
    args = parser.parse_args()
    entry = entry_for(args.repository.rstrip("/"), args.commit, args.path.strip("/"), args.category)
    target = ROOT / "plugins" / f"{entry['id']}.json"
    target.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {target.relative_to(ROOT)}: now run tools/build_index.py and tools/check.py {target.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
