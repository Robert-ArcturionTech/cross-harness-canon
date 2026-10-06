# ANTIGRAVITY.md → reviewer Boot

**Antigravity entry point for reviewer.** This is a pointer. All identity, voice, rules and tools load from a single manifest.

Read [`boot/home.md`](boot/home.md) first. It lists every file to load at boot, in order, plus the on-demand tiers.

Before answering anything substantive (about the project, a past decision, or another agent's context), query the knowledge service: `GET http://localhost:8080/query?topic=...` (HTTP fallback when no MCP). Never bulk-scan the notes folder.

Review notes are private to this agent by default. Never surface them to other agents without the owner's direction.

Everything else (review checklists, past findings) is **read on demand**, not at boot.

> **Rules** - the 3 project rules live in `rules/`. They bind every harness equally.

**This file is machine-generated** by `cross_harness_canon.py` from `registry.json` + `agents.json`. All 5 siblings (`CLAUDE.md` · `AGENTS.md` · `HERMES.md` · `GEMINI.md` · `ANTIGRAVITY.md`) carry a byte-identical body apart from three registry-driven lines. **Do not hand-edit**: a hand edit is drift and `--check` fails on it. Put doctrine in the boot manifest.
