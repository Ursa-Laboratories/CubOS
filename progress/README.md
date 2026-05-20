# Progress Notes

**Default: don't create one.** Most tasks don't need a progress file.

## When to create

Only for one of:
- Hardware-facing motion changes that span multiple commits.
- Refactors touching >5 files.
- Explicit handoff between sessions/contributors.

## Rules

- Filename: `YYYY-MM-DD-<short-slug>.md`.
- One page max. If it grows, promote durable notes to `docs/` and shrink this file.
- Sections: scope, changed files, validation, hardware impact, open risks, next steps.
- Delete on PR merge.

## History

Use `git log -- progress/` and commit messages instead of long-lived timeline files.
