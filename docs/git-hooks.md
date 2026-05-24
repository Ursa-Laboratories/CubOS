# Git Hooks

This repo includes tracked Git hook shims in `.githooks/` for the shared
`Ursa_Context` documentation guard.

Install them in this checkout:

```bash
./tools/install-git-hooks.sh
```

The installer sets `core.hooksPath=.githooks` and makes the hook files
executable.

The `pre-commit` hook runs `Ursa_Context/tools/ursa_doc_guard.py pre-commit`.
It blocks source/config commits that do not also include repo documentation or
durable workspace context updates. The `post-commit` hook records commit
metadata into `Ursa_Context/inbox/repo-updates.jsonl`.

By default the hooks expect `Ursa_Context` to be cloned next to this repo inside
the Hephaestus workspace. For another layout, set:

```bash
export URSA_CONTEXT_DIR=/path/to/Ursa_Context
```

Bypass the guard only for a deliberately docs-neutral commit:

```bash
URSA_DOC_GUARD_ALLOW_NO_DOCS=1 git commit
```

