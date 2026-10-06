# cross-harness-canon

Write your agent instructions **once**. Generate `CLAUDE.md`, `AGENTS.md`,
`GEMINI.md`, `HERMES.md` and `ANTIGRAVITY.md` from that one source, byte-identical
except for three registry-driven lines. A `--check` mode fails CI the moment any
file drifts or is hand-edited.

Python 3, standard library only, one file.

## Why this matters

Every AI coding harness reads its own boot file. Maintained by hand, those files
drift: a rule lands in `AGENTS.md` for a day and never reaches `CLAUDE.md`, and
"the same agent" quietly becomes two different agents depending on which tool
launched it. Nobody notices until the behavior diverges.

`cross-harness-canon` makes that drift impossible to ship:

- **One source of truth.** Doctrine lives in a boot manifest. The per-harness
  files are thin, *generated* pointers.
- **Byte-identical bodies.** Exactly three lines may differ per harness (title,
  entry-point sentence, one capability line), and all three come from a registry.
- **Drift is a failing exit code.** `--check` exits `1` on any difference, missing
  file or hand edit. `--parity` proves the five bodies match once the permitted
  lines are removed.
- **Adding a harness is one registry entry**, not a re-architecture.

## Quickstart

```bash
git clone https://github.com/ArcturionTechnologies/cross-harness-canon.git
cd cross-harness-canon

# 1. Generate the five files for every agent in the bundled example
python3 cross_harness_canon.py --project examples/basic --apply

# 2. Verify nothing drifted (exit 0 = clean)
python3 cross_harness_canon.py --project examples/basic --check

# 3. Prove the five bodies are identical modulo the three permitted lines
python3 cross_harness_canon.py --project examples/basic --parity

# 4. Hand-edit one file, then watch the gate catch it
echo "a rule only Codex sees" >> examples/basic/roots/researcher/AGENTS.md
python3 cross_harness_canon.py --project examples/basic --check --diff   # exit 1
python3 cross_harness_canon.py --project examples/basic --apply          # repaired
```

What one generated file looks like (`examples/basic/roots/researcher/AGENTS.md`):

```markdown
# AGENTS.md → researcher Boot

**Codex / generic agent platforms entry point for the research agent.** This is a pointer. All identity, voice, rules and tools load from a single manifest.

Read [`boot/home.md`](boot/home.md) first. It lists every file to load at boot, in order, plus the on-demand tiers.

Before answering anything substantive (about the project, a past decision, or another agent's context), query the knowledge service: `kb_query(topic=...)` (MCP) · `GET http://localhost:8080/query?topic=...` · `kb-query "..."`. Never bulk-scan the notes folder.
...
```

The same file for `ANTIGRAVITY.md` differs in exactly three lines. The registry
marks that harness's MCP support as `gap`, so its capability line falls back to
`GET http://localhost:8080/query?topic=... (HTTP fallback when no MCP)`.

## Design

```
 registry.json  ──┐   which harnesses exist, entry filenames, capabilities
 agents.json    ──┤   shared defaults + the ONLY place per-agent clauses live
 bodies/*.md    ──┼──►  cross_harness_canon.py  ──►  <root-base>/<agent>/CLAUDE.md
 rules/ (counted) ─┤        render (pure)              <root-base>/<agent>/AGENTS.md
 include source  ─┘                                    <root-base>/<agent>/GEMINI.md
                                                       <root-base>/<agent>/HERMES.md
                         --check   on disk == generated?  <root-base>/<agent>/ANTIGRAVITY.md
                         --apply   write the files
                         --parity  hash(body minus 3 lines) equal across all 5?
```

Everything is rendered in memory first (`Context.render`), so `--check`, `--apply`
and `--parity` can never disagree about what "correct" means.

**The three varying lines**

| Line | Driven by |
| --- | --- |
| Title: `# <FILE>.md → <agent> Boot` | registry `entry_filename` |
| Entry sentence: `**<phrase> for <subject>.** This is a pointer.` | registry `entry_point_phrase` |
| Capability line | registry `capabilities.mcp`: `full` gets MCP plus HTTP, anything else gets HTTP only, marked as a fallback |

**Other behavior worth knowing**

- *Measured, not typed.* `measured` in `agents.json` counts files in a directory
  and injects the number (`{{measured.rules}}`). An empty or missing directory is a
  setup error, because a silently generated `0` is worse than a loud failure.
- *Projected blocks.* `include` pulls a block between two markers out of a source
  document. It fails if the markers are missing, duplicated or reversed.
- *Verbatim agents.* An agent that is a full manifest rather than a pointer sets
  `"template": "verbatim"` and keeps its own body, still byte-identical across
  all five files with zero varying lines.
- *Fail-closed registry.* A harness declared in the registry but missing from
  `order` is rejected rather than silently left unprojected.

## Project layout

```
cross_harness_canon.py        the whole tool
examples/basic/
  registry.json               five harnesses
  agents.json                 defaults + four example agents
  bodies/shared-notes.md      verbatim body example
  rules/                      counted on disk; operating-card.md is an include source
  roots/<agent>/boot/home.md  boot manifests (the real doctrine)
  roots/<agent>/*.md          the generated files, committed so CI can --check them
tests/test_canon.py           33 tests, stdlib unittest
```

## Using it in your own repo

1. Copy `examples/basic/` somewhere, or point `--project` at a directory with your
   own `registry.json` and `agents.json`.
2. Put each agent's boot manifest at `<root-base>/<agent>/boot/home.md` (or set
   `boot_pointer`).
3. Choose where agent roots live: `--root-base DIR`, or the `ARC_ROOT` environment
   variable, or `<project>/roots` by default.
4. Run `--apply` once, commit the generated files, and add `--check` to CI.

Exit codes: `0` clean, `1` drift, `2` setup error (unreadable config, missing root
or boot manifest, unknown placeholder).

To add a harness, add an entry to `registry.json` (`entry_filename`,
`entry_point_phrase`, `capabilities`), append its id to `order`, and re-run `--apply`.

## Tests

```bash
python3 -m unittest discover -s tests -v     # or: python3 -m pytest
```

## License

MIT. See [LICENSE](LICENSE).

Built by Robert Lingoes with AI coding agents (Claude Code / Codex); Robert owns the architecture, requirements and review.
