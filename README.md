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
| `name`, `description`, `version`, `api`, `permissions` | The same as in the plugin's `plugin.json` at that commit (CI compares). |
| `repository` | `https://github.com/<owner>/<repo>`. |
| `commit` | The full commit id t-code installs. Not a branch or a tag: those move. |
| `path` | The plugin's folder inside the repository (`""` for the top). |
| `tree-sha256` | The hash of that folder's files: `tools/tree_hash.py <folder>`. |
| `categories` | Free words for Browse's search: `languages`, `linters`, `formatters`, `documents`, `build`, `git`, `text`, `fun`, ... |
| `reviewed` | `false` from authors. A maintainer sets `true` after reading this exact commit. |

The tree hash is the sha256 of one line per regular file, sorted by path:
`<file's sha256> <x or -> <path>` (`x` when it is executable). It does not depend on how GitHub
compresses its archives. Symbolic links make a folder unfit.

## Publishing

1. Put the plugin in a public GitHub repository (a whole repository, or a folder in one).
2. At the commit you want to publish: `tools/tree_hash.py <plugin folder>`.
3. Add `plugins/<id>.json`, run `tools/build_index.py`, and commit both.
4. Open a pull request. CI checks it (below); when it passes, it is merged with `"reviewed": false`.

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

## Review

Passing CI means the rules hold, not that the plugin is safe. Until a maintainer has read the
commit, t-code marks the plugin **not reviewed yet** and warns three times: when it is installed
(it installs switched off), when it is first turned on, and when it first runs. A maintainer who has
read that exact commit sets `"reviewed": true`; t-code then drops the warnings for it.

Maintainers are listed in `MAINTAINERS`.

## Removing

A plugin that misbehaves is removed by deleting its entry. Installed copies stay where they are
(t-code never deletes on its own); Browse stops listing it, so it gets no more updates.
