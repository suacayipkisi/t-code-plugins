#!/usr/bin/env python3
"""index.json from plugins/*.json: what t-code's Plugins window reads.

    tools/build_index.py          write index.json
    tools/build_index.py --check  fail when index.json is not what it would write (CI)
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIELDS = ["id", "name", "provider", "description", "version", "api", "repository", "commit", "path",
          "tree-sha256", "permissions", "categories", "requires", "reviewed", "versions"]


def render(entries):
    """index.json's text for these entries (tools/guard.py reads them from git)."""
    plugins = [{k: entry[k] for k in FIELDS if k in entry} for entry in entries]
    plugins.sort(key=lambda e: e["id"])
    return json.dumps({"format": 1, "plugins": plugins}, indent=2, ensure_ascii=False) + "\n"


def build():
    return render(json.loads(path.read_text()) for path in sorted((ROOT / "plugins").glob("*.json")))


if __name__ == "__main__":
    text = build()
    index = ROOT / "index.json"
    if "--check" in sys.argv[1:]:
        if index.read_text() != text:
            sys.exit("index.json is out of date: run tools/build_index.py and commit it")
        print("index.json is up to date")
    else:
        index.write_text(text)
