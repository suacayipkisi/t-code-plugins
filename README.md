# t-code-plugins

The plugin registry of [t-code](https://github.com/suacayipkisi/t-code): what its Plugins window shows
under **Browse**. It holds **no plugin code**, only pins: for each plugin, the repository, the exact
commit and a hash of its files. t-code downloads that commit from GitHub, checks the hash, and only
then installs it.

How plugins work (the manifest, the socket, permissions): t-code's
[docs/plugins.md](https://github.com/suacayipkisi/t-code/blob/main/docs/plugins.md).

## An entry

`plugins/<id>.json`, one per plugin:

```json
{
  "id": "shellcheck",
  "name": "ShellCheck",
  "provider": "someone",
  "description": "ShellCheck's warnings in the Problems panel when a shell script is saved.",
  "version": "1.0.0",
  "api": "tapi_1",
  "repository": "https://github.com/someone/t-code-shellcheck",
  "commit": "0123456789abcdef0123456789abcdef01234567",
  "path": "",
  "tree-sha256": "00fcf7657b9e4b8639a3e83513e16d5ffc14a89fb93c05c8835f7fc708a25d79",
  "permissions": [],
  "categories": ["linters"],
  "reviewed": false
}
```

| Field | Meaning |
|---|---|
| `id` | The plugin's id, the file's name; lowercase letters, digits and `-`. |
| `name`, `description`, `version`, `api`, `permissions`, `requires` | The same as in the plugin's `plugin.json` at that commit (CI compares; `requires` only when the plugin has one, and `tools/new_entry.py` copies it). |
| `provider` | Who publishes the plugin, shown next to it in t-code: `plugin.json`'s `provider`, or the repository's owner when it has none (CI compares). |
| `repository` | `https://github.com/<owner>/<repo>`. |
| `commit` | The full commit id t-code installs. Not a branch or a tag: those move. |
| `path` | The plugin's folder inside the repository (`""` for the top). |
| `tree-sha256` | The hash of that folder's files: `tools/tree_hash.py <folder>`. |
| `categories` | Free words for Browse's search: `languages`, `linters`, `formatters`, `documents`, `build`, `git`, `text`, `fun`, ... |
| `reviewed` | `false` from authors. A maintainer sets `true` after reading this exact commit. |

The tree hash is the sha256 of one line per regular file, sorted by path:
`<file's sha256> <x or -> <path>` (`x` when it is executable). It does not depend on how GitHub
compresses its archives. Symbolic links make a folder unfit.

### Older t-codes: `versions`

A plugin update may need a newer plugin API (`"api": "tapi_1_1"`): an older t-code cannot load it.
`versions` lists the plugin's commits, oldest first, each with the API it needs:

```json
"versions": [
  {"commit": "0123…", "tree-sha256": "00fc…", "version": "1.0.0", "api": "tapi_1"},
  {"commit": "4567…", "tree-sha256": "9a1b…", "version": "2.0.0", "api": "tapi_1_1", "permissions": ["terminal"]}
]
```

- t-code 0.5.2 and newer install the newest row whose `api` they speak; when an even newer one needs a
  newer t-code, Browse says so instead of offering it as an update.
- The entry's own `commit`, `tree-sha256`, `version`, `api` (and `path`, `permissions`, `requires`)
  are what t-code 0.5.1 and older read: they have to be the **most compatible** row, the newest of
  the rows that need the oldest `api` (CI checks it).
- A row says `path`, `permissions` or `requires` when they differ from the entry's, and
  `"reviewed": true` only from a maintainer, like the entry.
- `tools/new_entry.py` on an existing entry adds the commit to `versions` and picks the pin itself.
  CI checks each new row's commit like the pin.

## Publishing

1. Put the plugin in a public GitHub repository (a whole repository, or a folder in one).
2. Push the commit you want to publish, then
   `tools/new_entry.py https://github.com/<owner>/<repo> <commit> [path] --category <word>`: it
   downloads that commit and writes `plugins/<id>.json` from its `plugin.json` and files (by hand:
   `tools/tree_hash.py <plugin folder>` gives `tree-sha256`).
3. Run `tools/build_index.py` and `tools/check.py plugins/<id>.json`, and commit the entry and
   `index.json`.
4. Open a pull request. CI checks it (below); when it passes, it is merged with `"reviewed": false`
   and a maintainer signs the new index (see [Signing](#signing)).

Updating is the same with a new `commit` and `tree-sha256`. A new commit always starts unreviewed.

## What CI checks

`tools/check.py`, on every pull request:

- the entry: its fields, and that only a maintainer turns `reviewed` on;
- the commit: it downloads, has a `plugin.json` that matches the entry, and its files match
  `tree-sha256`;
- no binaries (images aside), no symbolic links, no `curl ... | sh`;
- network use (curl, wget, ssh, urllib, fetch, ...) only with the `network` permission; talking to
  t-code's own socket does not count;
- shell scripts pass `shellcheck`;
- a smoke test: each command (and `start`) runs against a fake t-code socket; a program that cannot
  even start fails.

`python3 tools/test_tools.py` tests the tools themselves.

A second check, `guard` (`tools/guard.py`), runs the rules from `main`, not from the pull request,
so a pull request cannot change what it is checked by. It reads the pull request as data and runs
none of it:

- only maintainers change anything outside `plugins/` and `index.json` (tools, workflows,
  `MAINTAINERS`, this README) or remove an entry;
- the entries' fields and `reviewed`, with `MAINTAINERS` as it is on `main`;
- `index.json` is exactly what `tools/build_index.py` makes from the entries.

## Review

Passing CI means the rules hold, not that the plugin is safe. Until a maintainer has read the
commit, t-code marks the plugin **not reviewed yet** and warns three times: when it is installed
(it installs switched off), when it is first turned on, and when it first runs. A maintainer who has
read that exact commit sets `"reviewed": true`; t-code then drops the warnings for it.

Maintainers are listed in `MAINTAINERS`.

## Signing

t-code trusts `index.json` only with a good `index.json.sig` beside it: an Ed25519 signature over
its exact bytes, by the key in `PUBLIC_KEY` (t-code holds the same key). When the signature is
missing or does not match, t-code keeps showing the last index it checked and says why.

After merging anything that changes `index.json`, a maintainer signs it again and pushes the
signature:

```sh
tools/sign_index.py ~/.config/t-code-registry/signing-key   # writes index.json.sig
tools/sign_index.py --check                                  # what CI runs on main
```

The signing key never goes to GitHub, not even as a secret: whoever holds it decides what every
t-code installs. `tools/sign_index.py --new-key <file>` makes one and prints its public key, for
`PUBLIC_KEY` and t-code's `REGISTRY_PUBLIC_KEY`; a new key needs a t-code release that carries it.
Only maintainers change `index.json.sig` and `PUBLIC_KEY` (they are outside `plugins/`).

## Removing

A plugin that misbehaves is removed by deleting its entry. Installed copies stay where they are
(t-code never deletes on its own); Browse stops listing it, so it gets no more updates.
