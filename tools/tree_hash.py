#!/usr/bin/env python3
"""The tree hash of a plugin's folder, as t-code checks it (src/plugins/registry.c).

One line per regular file, sorted by its path's bytes: "<sha256 of the file> <x or -> <path>\\n"
(x: any executable bit). The tree hash is the sha256 of those lines. Symbolic links and other
special files make a folder unfit.

    tools/tree_hash.py <folder>
"""
import hashlib
import os
import stat
import sys


class Unfit(Exception):
    pass


def tree_hash(top):
    files = []
    for folder, dirs, names in os.walk(top, followlinks=False):
        for name in dirs + names:
            path = os.path.join(folder, name)
            mode = os.lstat(path).st_mode
            inside = os.path.relpath(path, top).replace(os.sep, "/")
            if stat.S_ISREG(mode):
                files.append((inside.encode(), path, mode))
            elif not stat.S_ISDIR(mode):
                raise Unfit(f"{inside} is a link or a special file: plugins hold plain files only")
    tree = hashlib.sha256()
    for inside, path, mode in sorted(files):
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        flag = "x" if mode & 0o111 else "-"
        tree.update(f"{digest} {flag} ".encode() + inside + b"\n")
    return tree.hexdigest()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        print(tree_hash(sys.argv[1]))
    except Unfit as e:
        sys.exit(str(e))
