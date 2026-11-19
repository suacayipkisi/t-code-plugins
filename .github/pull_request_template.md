<!-- Adding or updating a plugin: one plugins/<id>.json per pull request. -->

- **Plugin:** <!-- id and one sentence -->
- **Repository / commit:** <!-- https://github.com/<owner>/<repo> at <full commit id> -->
- **What it runs:** <!-- its programs, what they call (git, python3, ...) -->
- **Network:** <!-- what it talks to, if it declares "network" -->

- [ ] `tree-sha256` from `tools/tree_hash.py <plugin folder>` at that commit
- [ ] `tools/build_index.py` run, `index.json` committed
- [ ] `"reviewed": false` (a maintainer sets it after reading the commit)
