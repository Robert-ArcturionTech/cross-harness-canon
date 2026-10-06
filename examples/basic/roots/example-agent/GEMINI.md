# GEMINI.md → example-agent Boot

**Gemini CLI entry point for example-agent.** This is a pointer. All identity, voice, rules and tools load from a single manifest.

Read [`boot/home.md`](boot/home.md) first. It lists every file to load at boot, in order, plus the on-demand tiers.

Before answering anything substantive (about the project, a past decision, or another agent's context), query the knowledge service: `kb_query(topic=...)` (MCP) or `GET http://localhost:8080/query?topic=...`. Never bulk-scan the notes folder.

**Review contract:** before recommending a risky or irreversible change, gather current evidence, state the trade-offs, and wait for explicit approval before acting.

Everything else (memory, domain notes, catalogs) is **read on demand**, not at boot. The manifest explains the triggers.

> **Rules** - the 3 project rules live in `rules/`. They bind every harness equally.

**This file is machine-generated** by `cross_harness_canon.py` from `registry.json` + `agents.json`. All 5 siblings (`CLAUDE.md` · `AGENTS.md` · `HERMES.md` · `GEMINI.md` · `ANTIGRAVITY.md`) carry a byte-identical body apart from three registry-driven lines. **Do not hand-edit**: a hand edit is drift and `--check` fails on it. Put doctrine in the boot manifest.
