#!/usr/bin/env python3
"""The trusted half of the review: what a pull request may change, read from git, never run.

    tools/guard.py --base <git ref> --head <git ref> --actor <github login>

check.yml runs on `pull_request`, so it runs the pull request's own copy of the tools, MAINTAINERS and
workflow: a pull request could change them and pass. guard.yml runs this script on
`pull_request_target` instead: the workflow, this script, check.py's entry rules and MAINTAINERS all
come from the base branch, and the pull request is only data (git show), nothing of it is executed.

  - a maintainer (MAINTAINERS at the base) may change anything;
  - anyone else may only add or change plugins/<id>.json and index.json: no tools, workflows,
    MAINTAINERS or README, and no removed entries (a maintainer removes);
  - every added or changed entry passes check.py's entry rules ("reviewed" included), against the
    same file at the merge base;
  - index.json at the head is exactly what build_index.py makes from the head's entries.

Exit status 0 when all of it holds; the problems are printed, one per line.
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_index  # noqa: E402
import check  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENTRY = re.compile(r"^plugins/[^/]+\.json$")


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout


def show(repo, ref, path):
    """A file's text at ref, or None when it is not there."""
    done = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=repo, capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else None


def head_index(repo, head):
    """index.json as build_index.py would write it from the head's entries."""
    entries = []
    for name in git(repo, "ls-tree", "--name-only", head, "plugins/").split():
        if ENTRY.match(name):
            entries.append(json.loads(show(repo, head, name)))
    return build_index.render(entries)


def guard(repo, base, head, actor):
    """Problems with the pull request from base to head (both git refs in repo)."""
    problems = []
    fork = git(repo, "merge-base", base, head).strip()
    maintainer = actor in check.maintainers()
    for line in git(repo, "diff", "--name-status", "--no-renames", fork, head).splitlines():
        status, name = line.split("\t", 1)
        if maintainer:
            pass
        elif status == "D" and ENTRY.match(name):
            problems.append(f"{name}: only a maintainer removes an entry")
        elif not ENTRY.match(name) and name != "index.json":
            problems.append(f"{name}: only a maintainer changes files outside plugins/ and index.json")
        if status == "D" or not ENTRY.match(name):
            continue
        try:
            entry = json.loads(show(repo, head, name))
        except ValueError as e:
            problems.append(f"{name}: not JSON: {e}")
            continue
        old = show(repo, fork, name)
        try:
            old = json.loads(old) if old else None
        except ValueError:
            old = None
        problems += [f"{name}: {p}" for p in check.check_entry(pathlib.Path(name), entry, old, actor)]
    try:
        if show(repo, head, "index.json") != head_index(repo, head):
            problems.append("index.json is out of date: run tools/build_index.py and commit it")
    except (ValueError, KeyError) as e:
        problems.append(f"index.json: an entry cannot be read ({e})")
    return problems


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--actor", required=True)
    args = parser.parse_args()
    problems = guard(ROOT, args.base, args.head, args.actor)
    for p in problems:
        print(p)
    if not problems:
        print("ok")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
