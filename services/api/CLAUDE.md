# CubOS API Contributor Notes

Read `AGENTS.md` and `docs/agent-index.md` before changing this service.

`cubos_api` is the monorepo's sole FastAPI backend. It exposes `/api/v1` to
both `apps/operator-web/` and `sdk/python/` and delegates runtime behavior to
the installed `cubos` package in `packages/core/`.

Do not duplicate runtime validation, motion, protocol, deck, or instrument
logic in the API or its clients. Do not use sibling-path import hacks. Never
exercise real motion or protocol execution as part of automated testing.
