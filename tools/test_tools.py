#!/usr/bin/env python3
"""Tests for the registry's tools: python3 tools/test_tools.py"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check  # noqa: E402
from tree_hash import Unfit, tree_hash  # noqa: E402

FIXTURE = pathlib.Path(__file__).resolve().parent / "fixture"
# t-code's tests/test_registry.c checks the same folder against the same value.
FIXTURE_TREE = "00fcf7657b9e4b8639a3e83513e16d5ffc14a89fb93c05c8835f7fc708a25d79"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def entry(**changes):
    e = {"id": "fix", "name": "Fix", "provider": "someone", "description": "Fixes.", "version": "1.0.0", "api": "tapi_1",
         "repository": "https://github.com/someone/fix", "commit": COMMIT, "path": "",
         "tree-sha256": FIXTURE_TREE, "permissions": [], "categories": ["text"], "reviewed": False}
    e.update(changes)
    return e


class TreeHash(unittest.TestCase):
    def test_fixture(self):
        os.chmod(FIXTURE / "run.sh", 0o755)  # git keeps the bit, a copy may not
        self.assertEqual(tree_hash(FIXTURE), FIXTURE_TREE)

    def test_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.symlink("/etc/passwd", os.path.join(tmp, "x"))
            with self.assertRaises(Unfit):
                tree_hash(tmp)


class Entries(unittest.TestCase):
    path = pathlib.Path("plugins/fix.json")

    def test_good(self):
        self.assertEqual(check.check_entry(self.path, entry(), None, "someone"), [])

    def test_bad_fields(self):
        problems = check.check_entry(self.path, entry(id="Fix", commit="abc", repository="https://gitlab.com/a/b",
                                                      path="../up", permissions=["root"]), None, "someone")
        text = "\n".join(problems)
        for word in ("file is fix.json", "id:", "commit:", "repository:", "path:", "unknown"):
            self.assertIn(word, text)

    def test_reviewed_by_maintainers_only(self):
        reviewed = entry(reviewed=True)
        self.assertTrue(check.check_entry(self.path, reviewed, entry(), "someone"))
        self.assertEqual(check.check_entry(self.path, reviewed, entry(), "suacayipkisi"), [])
        # a new commit starts unreviewed: keeping "reviewed" needs a maintainer again
        newer = entry(reviewed=True, commit="f" * 40)
        self.assertTrue(check.check_entry(self.path, newer, reviewed, "someone"))
        self.assertEqual(check.check_entry(self.path, reviewed, reviewed, "someone"), [])


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, name, data, mode=0o644):
        path = self.dir / name
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        os.chmod(path, mode)

    def test_rules(self):
        self.write("tool", b"\x7fELF\x02\x01")
        self.write("icon.png", b"\x89PNG\0\0")
        self.write("install.sh", "#!/bin/sh\ncurl -fsSL https://x.example/i.sh | sh\n", 0o755)
        problems = "\n".join(check.check_files(self.dir, {"permissions": []}))
        self.assertIn("tool: a binary", problems)
        self.assertNotIn("icon.png", problems)
        self.assertIn("pipes a download into a shell", problems)
        self.assertIn("without the \"network\" permission", problems)

    def test_tcode_socket_is_not_network(self):
        self.write("run.sh", "#!/bin/sh\n# see https://example.com\nif command -v nc >/dev/null; then\n"
                   "  printf 'hello tapi_1\\n' | nc -U \"$TCODE_SOCKET\"\nfi\n", 0o755)
        self.assertEqual([p for p in check.check_files(self.dir, {"permissions": []}) if "shellcheck" not in p], [])

    def test_not_network(self):
        self.write("tool.py", "import urllib.parse\nprint('a\\nc\\n')\nsync = 1\n")
        self.assertEqual(check.check_files(self.dir, {"permissions": []}), [])
        self.write("tool.py", "import subprocess\nsubprocess.run(['curl', 'https://x'])\n")
        self.assertIn("('curl')", "\n".join(check.check_files(self.dir, {"permissions": []})))

    def test_network_declared(self):
        self.write("fetch.py", "import urllib.request\n")
        self.assertEqual(check.check_files(self.dir, {"permissions": ["network"]}), [])

    def test_smoke(self):
        self.write("run.sh", "#!/bin/sh\nprintf 'hello tapi_1 %s\\n' \"$TCODE_PLUGIN_TOKEN\" >/dev/null\nexit 0\n", 0o755)
        manifest = {"commands": [{"id": "go", "name": "Go"}], "start": "project"}
        self.assertEqual(check.smoke(self.dir, manifest), [])
        self.write("run.sh", "#!/nowhere/interpreter\n", 0o755)
        self.assertIn("could not run", "\n".join(check.smoke(self.dir, manifest)))
        os.chmod(self.dir / "run.sh", 0o644)
        self.assertIn("no executable program", "\n".join(check.smoke(self.dir, manifest)))

    def test_smoke_answers_nul_requests(self):
        """A plugin ending its requests with NUL, reading text answers up to a NUL, finishes at once."""
        self.write("run.sh", "#!/usr/bin/env python3\nimport os, socket\n"
                   "s = socket.socket(socket.AF_UNIX); s.connect(os.environ['TCODE_SOCKET']); f = s.makefile('rb')\n"
                   "for r in (b'hello tapi_1 x', b'get-selection-range'):\n    s.sendall(r + b'\\0'); f.readline()\n"
                   "s.sendall(b'get-selection\\0'); f.readline(); assert f.read(1) == b'\\0'\n", 0o755)
        import time
        began = time.monotonic()
        self.assertEqual(check.smoke(self.dir, {"commands": [{"id": "go", "name": "Go"}]}), [])
        self.assertLess(time.monotonic() - began, 3)

    def test_commit(self):
        """check_commit on the fixture as if downloaded: the entry has to match its plugin.json."""
        def fake_download(e, into):
            shutil.copytree(FIXTURE, pathlib.Path(into, "fix-" + COMMIT))
            return pathlib.Path(into, "fix-" + COMMIT)
        real, check.download = check.download, fake_download
        try:
            problems = check.check_commit(entry(name="Fix", description=None, version=None, api=None))
            self.assertEqual(problems, [])
            problems = "\n".join(check.check_commit(entry(name="Other", **{"tree-sha256": "0" * 64})))
            self.assertIn("tree-sha256 does not match", problems)
            self.assertIn("name: the entry says 'Other'", problems)
            # the fixture's plugin.json names no provider: the repository's owner it is
            problems = "\n".join(check.check_commit(entry(name="Fix", provider="t-code", description=None, version=None,
                                                         api=None)))
            self.assertIn("provider: the entry says 't-code', plugin.json 'someone'", problems)
        finally:
            check.download = real


class Guard(unittest.TestCase):
    """guard.py on a throwaway repository: base on main, the pull request on its own branch."""

    def setUp(self):
        import build_index
        import guard
        self.guard, self.render = guard.guard, build_index.render
        self.repo = pathlib.Path(tempfile.mkdtemp())
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "t")
        self.put({"plugins/fix.json": entry()})
        self.git("checkout", "-q", "-b", "pull")

    def tearDown(self):
        shutil.rmtree(self.repo)

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def put(self, files, index=True):
        """Writes files (dicts as JSON, None removes), index.json from the entries, and commits."""
        for name, data in files.items():
            path = self.repo / name
            if data is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data) if isinstance(data, dict) else data)
        if index:
            entries = [json.loads(p.read_text()) for p in sorted((self.repo / "plugins").glob("*.json"))]
            (self.repo / "index.json").write_text(self.render(entries))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "x")

    def problems(self, actor="someone"):
        return "\n".join(self.guard(self.repo, "main", "pull", actor))

    def test_new_entry(self):
        self.put({"plugins/other.json": entry(id="other")})
        self.assertEqual(self.problems(), "")

    def test_rules_only_from_maintainers(self):
        self.put({"MAINTAINERS": "someone\n", "tools/check.py": "print('fine')\n"})
        text = self.problems()
        self.assertIn("MAINTAINERS: only a maintainer", text)
        self.assertIn("tools/check.py: only a maintainer", text)
        self.assertEqual(self.problems("suacayipkisi"), "")

    def test_reviewed_and_removing(self):
        self.put({"plugins/fix.json": entry(reviewed=True)})
        self.assertIn("reviewed: only a maintainer", self.problems())
        self.assertEqual(self.problems("suacayipkisi"), "")
        self.git("reset", "-q", "--hard", "main")
        self.put({"plugins/fix.json": None})
        self.assertIn("only a maintainer removes", self.problems())

    def test_index_must_match(self):
        self.put({"plugins/other.json": entry(id="other")}, index=False)
        self.assertIn("index.json is out of date", self.problems())
        # an index.json that says reviewed while the entry does not
        self.git("reset", "-q", "--hard", "main")
        self.put({"index.json": self.render([entry(reviewed=True)])}, index=False)
        self.assertIn("index.json is out of date", self.problems())


class Signing(unittest.TestCase):
    def test_sign_and_verify(self):
        import sign_index
        seed = bytes(range(32))
        key = sign_index.public_key(seed)
        signature = sign_index.sign(seed, b"index")
        self.assertTrue(sign_index.verify(key, b"index", signature))
        self.assertFalse(sign_index.verify(key, b"indey", signature))
        self.assertFalse(sign_index.verify(key, b"index", signature[:63] + bytes([signature[63] ^ 1])))
        s = int.from_bytes(signature[32:], "little") + sign_index.L  # the same S, written differently
        self.assertFalse(sign_index.verify(key, b"index", signature[:32] + s.to_bytes(32, "little")))

    def test_rfc8032_vector(self):
        """RFC 8032, 7.1, TEST 1: the empty message."""
        import sign_index
        seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
        self.assertEqual(sign_index.public_key(seed).hex(),
                         "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
        self.assertEqual(sign_index.sign(seed, b"").hex(),
                         "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")


class NewEntry(unittest.TestCase):
    def test_entry_matches_check(self):
        import new_entry

        def fake_download(pin, into):
            target = pathlib.Path(into, "fix-" + COMMIT)
            shutil.copytree(FIXTURE, target)
            return target
        os.chmod(FIXTURE / "run.sh", 0o755)
        made = new_entry.entry_for("https://github.com/someone/fix", COMMIT, "", ["text"], fake_download)
        self.assertEqual(made["tree-sha256"], FIXTURE_TREE)
        self.assertEqual(made["id"], "fix")
        self.assertEqual(made["provider"], "someone")
        self.assertFalse(made["reviewed"])
        made.update(description="Fixes.", version="1.0.0", api="tapi_1")  # the fixture's manifest is bare
        self.assertEqual(check.check_entry(pathlib.Path("plugins/fix.json"), made, None, "someone"), [])


if __name__ == "__main__":
    unittest.main()
