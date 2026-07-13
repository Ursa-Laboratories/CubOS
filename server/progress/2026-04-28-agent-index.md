# 2026-04-28 Agent index docs

## Work done

- Added `docs/agent-index.md` as a compact retrieval map for Zoo coding agents.
- Added a short `AGENTS.md` section pointing agents to the retrieval index before coding.
- Added a `CLAUDE.md` retrieval rule so Claude-style agents read the same index.

## Why

The Vercel AGENTS.md eval writeup suggests always-loaded project context and compact doc indexes are more reliable than optional skill invocation for general framework/project knowledge. Zoo depends on CubOS boundaries that agents should retrieve from repo docs/source instead of guessing.

## Verification

Docs-only change. Verified by direct inspection and repository grep for the new routing section.

## Hardware impact

No hardware behavior changed. No physical hardware validation required.
