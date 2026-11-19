#!/usr/bin/env python3
"""The registry's automatic review: checks plugins/<id>.json entries and the commits they pin.

    tools/check.py [--actor <github login>] [--base <git ref>] [entry.json ...]

Without entries it checks the ones changed since --base (every entry when there is no base). For
each entry:

  - the entry itself: id (= file name), repository on github.com, a 40-digit commit, a 64-digit
    tree-sha256, a path inside the repository, lists of strings;
  - "reviewed": true only from a maintainer (MAINTAINERS); a new commit starts unreviewed;
  - the commit's archive: its plugin folder has a plugin.json whose id, name, version, api and
    permissions match the entry, and its tree hash matches tree-sha256;
  - no symbolic links, no binaries (images aside), no "curl ... | sh";
  - network use (curl, wget, nc, ssh, urllib, fetch, ...) only with the "network" permission; talking
    to t-code's own socket ($TCODE_SOCKET, nc -U, socat UNIX-CONNECT) is not network use;
  - shell scripts pass shellcheck;
  - a smoke test: each command (and "start") runs against a fake t-code socket that answers "ok";
    a program that cannot even start (missing interpreter, not executable) fails.

Exit status 0 when every entry passes; the problems are printed, one per line.
"""
import argparse
import hashlib
import io
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from tree_hash import Unfit, tree_hash  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
PERMISSIONS = {"edit", "terminal", "network", "start"}
IMAGES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp"}
ID = re.compile(r"^[a-z0-9][a-z0-9-]*$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PIPE_TO_SHELL = re.compile(r"(curl|wget)[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b")
NETWORK = re.compile(
    r"(?:^|[\s;|&(`'\"\[])(curl|wget|nc|ncat|ssh|scp|rsync|telnet)(?=[\s'\"]|$)"  # as a program
    r"|\burllib\.request\b|\burlopen\(|\brequests\.(get|post|put|delete|head)\(|\bhttp\.client\b"  # Python
    r"|\bsocket\.create_connection\(|\bfetch\(|\bhttps?\.(get|request)\(")  # Python, JavaScript
# Lines that only talk to t-code's own socket, or look whether a program is there.
LOCAL = re.compile(r"TCODE_SOCKET|\s-U\b|UNIX-CONNECT|AF_UNIX|command -v|\bwhich\b|^\s*#")


def network_use(text):
    """The first line's network program or call, or None (t-code's socket does not count)."""
    for line in text.splitlines():
        hit = NETWORK.search(line)
        if hit and not LOCAL.search(line):
            return hit.group(0).strip(" \t;|&(`'\"[")
    return None


def maintainers():
    return {line.strip() for line in (ROOT / "MAINTAINERS").read_text().splitlines() if line.strip()}


def strings(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def check_entry(path, entry, old, actor):
    """Problems with the entry itself (old: the same file at --base, or None)."""
    problems = []
    if path.stem != entry.get("id"):
        problems.append(f"the file is {path.name} but its id is {entry.get('id')!r}")
    if not isinstance(entry.get("id"), str) or not ID.match(entry["id"]):
        problems.append("id: lowercase letters, digits and -")
    repo = entry.get("repository", "")
    if not isinstance(repo, str) or not re.match(r"^https://github\.com/[\w.-]+/[\w.-]+$", repo):
        problems.append("repository: https://github.com/<owner>/<repo>")
    if not isinstance(entry.get("commit"), str) or not HEX40.match(entry["commit"]):
        problems.append("commit: 40 lowercase hex digits (a full commit id)")
    if not isinstance(entry.get("tree-sha256"), str) or not HEX64.match(entry["tree-sha256"]):
        problems.append("tree-sha256: 64 lowercase hex digits (tools/tree_hash.py <plugin folder>)")
    sub = entry.get("path", "")
    if not isinstance(sub, str) or sub.startswith("/") or ".." in sub.split("/"):
        problems.append("path: a folder inside the repository")
    for key in ("permissions", "categories"):
        if key in entry and not strings(entry[key]):
            problems.append(f"{key}: a list of strings")
    unknown = set(entry.get("permissions") or []) - PERMISSIONS
    if unknown:
        problems.append(f"permissions: unknown {sorted(unknown)}")
    for key in ("name", "description", "version", "api"):
        if not isinstance(entry.get(key), str) or not entry[key]:
            problems.append(f"{key}: a string (the same as in plugin.json)")
    reviewed = entry.get("reviewed", False)
    if not isinstance(reviewed, bool):
        problems.append("reviewed: true or false")
    was_reviewed = bool(old and old.get("reviewed") and old.get("commit") == entry.get("commit"))
    if reviewed and not was_reviewed and actor not in maintainers():
        problems.append("reviewed: only a maintainer sets it to true, after reading this exact commit")
    return problems


def download(entry, into):
    """Unpacks the commit's archive into `into`; returns the plugin's folder."""
    url = f"{entry['repository']}/archive/{entry['commit']}.tar.gz"
    with urllib.request.urlopen(url, timeout=60) as answer:
        data = answer.read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        archive.extractall(into, filter="data")
    tops = os.listdir(into)
    if len(tops) != 1:
        raise Unfit("the archive does not hold one folder")
    return pathlib.Path(into, tops[0], entry.get("path", ""))


def scripts(folder):
    """The shell scripts in folder (by extension or #! line)."""
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        head = path.read_bytes()[:64]
        if path.suffix == ".sh" or re.match(rb"#!\s*/(usr/)?bin/(env\s+)?(ba|da)?sh\b", head):
            yield path


def check_files(folder, manifest):
    problems = []
    network = "network" in (manifest.get("permissions") or [])
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        inside = path.relative_to(folder)
        data = path.read_bytes()
        if path.suffix.lower() in IMAGES:
            continue
        if b"\0" in data or data.startswith(b"\x7fELF"):
            problems.append(f"{inside}: a binary; plugins are source the reviewers can read")
            continue
        text = data.decode("utf-8", "replace")
        if PIPE_TO_SHELL.search(text):
            problems.append(f"{inside}: pipes a download into a shell")
        if not network and path.suffix not in {".md", ".json", ".txt", ".lang", ".snippets"}:
            hit = network_use(text)
            if hit:
                problems.append(f"{inside}: uses the network ({hit!r}) without the \"network\" permission")
    if shutil.which("shellcheck"):
        for script in scripts(folder):
            result = subprocess.run(["shellcheck", "-S", "warning", str(script)], capture_output=True, text=True)
            if result.returncode:
                problems.append(f"{script.relative_to(folder)}: shellcheck:\n{result.stdout.strip()}")
    else:
        print("warning: shellcheck is not installed: shell scripts not checked", file=sys.stderr)
    return problems


# What the fake t-code answers, by command; "ok" for the rest. Text answers end with a NUL.
FAKE_ANSWERS = {"get-text": b"ok\n\0", "get-selection": b"ok\n\0", "get-cursor": b"ok 1 1\n",
                "get-selection-range": b"ok 1 1 1 1\n", "hello": b"ok tapi_1 t-code smoke\n"}


def fake_answers(c):
    """Answers one connection's requests, ended by a line break or a NUL (like t-code's)."""
    pending = b""
    try:
        with c:
            while True:
                data = c.recv(4096)
                if not data:
                    return
                pending += data
                while True:
                    cut = min((i for i in (pending.find(b"\0"), pending.find(b"\n")) if i >= 0), default=-1)
                    if cut < 0:
                        break
                    request, pending = pending[:cut], pending[cut + 1:]
                    command = request.split(b" ", 1)[0].decode("utf-8", "replace")
                    if command:
                        c.sendall(FAKE_ANSWERS.get(command, b"ok\n"))
    except OSError:
        pass  # the plugin went away


def fake_socket(path, stop):
    """A t-code that says yes to everything."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(8)
    server.settimeout(0.2)
    while not stop.is_set():
        try:
            conn, _ = server.accept()
        except socket.timeout:
            continue
        threading.Thread(target=fake_answers, args=(conn,), daemon=True).start()
    server.close()


def smoke(folder, manifest):
    problems = []
    executable = manifest.get("executable")
    candidates = [executable] if executable else ["run.sh", "plugin", folder.name]
    program = next(((folder / c).resolve() for c in candidates if c and (folder / c).is_file()), None)
    commands = [c.get("id") for c in manifest.get("commands") or [] if isinstance(c, dict)]
    if manifest.get("start") == "project":
        commands.append("start")
    if not commands:
        return problems
    if not program or not os.access(program, os.X_OK):
        return [f"no executable program for its commands ({executable or 'run.sh, plugin or ' + folder.name})"]
    with tempfile.TemporaryDirectory() as tmp:
        sock = os.path.join(tmp, "t-code.sock")
        stop = threading.Event()
        threading.Thread(target=fake_socket, args=(sock, stop), daemon=True).start()
        env = dict(os.environ, TCODE_SOCKET=sock, TCODE_API="tapi_1", TCODE_PLUGIN_ID=manifest.get("id", folder.name),
                   TCODE_PLUGIN_TOKEN="smoke", TCODE_ACTIVE_FILE="", TCODE_PROJECT_ROOT=tmp)
        for command in commands:
            try:
                result = subprocess.run([str(program), command, ""], cwd=folder, env=dict(env, TCODE_COMMAND_ID=command),
                                        capture_output=True, text=True, timeout=5)
                if result.returncode in (126, 127) or result.returncode < 0:
                    problems.append(f"smoke test: {command} could not run (status {result.returncode}): "
                                    f"{result.stderr.strip()[:300]}")
            except subprocess.TimeoutExpired:
                pass  # a start program that keeps running is fine
            except OSError as e:  # a missing interpreter, a bad format
                problems.append(f"smoke test: {command} could not run: {e.strerror}")
        stop.set()
    return problems


def check_commit(entry):
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        try:
            folder = download(entry, tmp)
            manifest_path = folder / "plugin.json"
            if not manifest_path.is_file():
                return [f"no plugin.json at {entry.get('path') or 'the top'} of that commit"]
            manifest = json.loads(manifest_path.read_text())
            if tree_hash(folder) != entry["tree-sha256"]:
                problems.append("tree-sha256 does not match that commit's plugin folder")
        except (Unfit, OSError, ValueError, tarfile.TarError) as e:
            return [f"the commit cannot be checked: {e}"]
        same = {"id": manifest.get("id", folder.name), "name": manifest.get("name"),
                "version": manifest.get("version"), "api": manifest.get("api"),
                "description": manifest.get("description")}
        for key, value in same.items():
            if value != entry.get(key):
                problems.append(f"{key}: the entry says {entry.get(key)!r}, plugin.json {value!r}")
        if sorted(manifest.get("permissions") or []) != sorted(entry.get("permissions") or []):
            problems.append("permissions: not the same as plugin.json's")
        problems += check_files(folder, manifest)
        problems += smoke(folder, manifest)
    return problems


def changed(base):
    names = subprocess.run(["git", "diff", "--name-only", "--diff-filter=AM", base, "--", "plugins/"],
                           cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / n for n in names if n.endswith(".json")]


def at_base(base, path):
    if not base:
        return None
    shown = subprocess.run(["git", "show", f"{base}:{path.relative_to(ROOT)}"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(shown.stdout) if shown.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", default=os.environ.get("GITHUB_ACTOR", ""))
    parser.add_argument("--base")
    parser.add_argument("--offline", action="store_true", help="check the entries only, not their commits")
    parser.add_argument("entries", nargs="*")
    args = parser.parse_args()
    paths = [pathlib.Path(e).resolve() for e in args.entries] or \
        (changed(args.base) if args.base else sorted((ROOT / "plugins").glob("*.json")))
    failed = False
    for path in paths:
        try:
            entry = json.loads(path.read_text())
        except ValueError as e:
            print(f"{path.name}: not JSON: {e}")
            failed = True
            continue
        problems = check_entry(path, entry, at_base(args.base, path), args.actor)
        if not problems and not args.offline:
            problems = check_commit(entry)
        for p in problems:
            print(f"{path.name}: {p}")
        failed |= bool(problems)
        if not problems:
            print(f"{path.name}: ok")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
