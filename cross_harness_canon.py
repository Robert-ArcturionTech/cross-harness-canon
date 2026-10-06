#!/usr/bin/env python3
"""cross-harness-canon: one canonical agent-instructions body, many harness files.

AI coding harnesses each read their own boot file: ``CLAUDE.md`` (Claude Code),
``AGENTS.md`` (Codex and generic agent platforms), ``GEMINI.md`` (Gemini CLI),
``HERMES.md`` and ``ANTIGRAVITY.md``. Maintained by hand, those files drift: a
rule lands in one and not the others, and "the same agent" quietly becomes
several different agents depending on which tool launched it.

This tool removes the drift by construction. The files are *generated* from one
canonical source, and the bodies are byte-identical across harnesses. Exactly
three lines may differ, and all three are driven by the harness registry, never
by hand:

  1. the title line          -  ``# <HARNESS>.md -> <AGENT> Boot``
  2. the entry-point sentence -  from the registry's ``entry_point_phrase``
  3. one capability line      -  ``capabilities.mcp == "full"`` gets the MCP call
                                 plus the HTTP path; anything else gets HTTP
                                 only, annotated as a fallback

Inputs live in a *project directory* (see ``examples/basic``):

  registry.json   which harnesses exist, their entry filenames and capabilities
  agents.json     shared defaults + per-agent variation (the ONLY place a
                  per-agent clause may live)
  bodies/         optional verbatim bodies for agents that are a full manifest
                  rather than a pointer
  rules/ ...      optional directories whose file counts are measured on disk
                  and injected into the text, so counts are never typed by hand

Agent roots (where the generated files are written) live under ``--root-base``,
which defaults to the ``ARC_ROOT`` environment variable, then to
``<project>/roots``. Each agent's root is ``<root-base>/<agent-name>``.

Usage
-----
    cross_harness_canon.py --project DIR --check            # exit 1 on any drift (default)
    cross_harness_canon.py --project DIR --check --diff     # ...and show unified diffs
    cross_harness_canon.py --project DIR --apply            # write the files
    cross_harness_canon.py --project DIR --apply --stage D  # render into D/<agent>/ only
    cross_harness_canon.py --project DIR --parity           # hash each body modulo the 3 lines
    cross_harness_canon.py --project DIR --parity --on-disk # same, but read the real files

Exit codes (CI relies on these):
    0  everything matches the generated source
    1  at least one file differs, is missing, or is unreadable (drift)
    2  setup error: registry/agents unreadable, or a root/boot pointer is missing
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import re
import sys
from pathlib import Path

TOOL_NAME = Path(__file__).name

# Placeholders available in ``shared_tail`` / ``include`` text: ``{{name}}``.
_PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.\-]+)\s*\}\}")


class SetupError(RuntimeError):
    """Unrecoverable: the generator cannot know what to write."""


# -- sources -----------------------------------------------------------------

def load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"unreadable {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise SetupError(f"{path.name} must contain a JSON object")
    return data


def load_registry(project: Path) -> dict:
    """Validate the harness registry and return it with a resolved ``order``."""
    registry = load_json(project / "registry.json")
    harnesses = registry.get("harnesses")
    if not isinstance(harnesses, dict) or not harnesses:
        raise SetupError("registry.json has no harnesses object")
    order = registry.get("order") or list(harnesses)
    for hid in order:
        entry = harnesses.get(hid)
        if not isinstance(entry, dict):
            raise SetupError(f"registry.json 'order' names unknown harness {hid!r}")
        for key in ("entry_filename", "entry_point_phrase", "capabilities"):
            if key not in entry:
                raise SetupError(f"harness {hid!r} is missing {key!r}")
    # A harness present in the registry but absent from `order` would be
    # silently unprojected, which is exactly the drift this tool exists to stop.
    unprojected = set(harnesses) - set(order)
    if unprojected:
        raise SetupError(
            f"registry.json declares harnesses missing from 'order': {sorted(unprojected)}"
        )
    names = [harnesses[h]["entry_filename"] for h in order]
    if len(set(names)) != len(names):
        raise SetupError("two harnesses share the same entry_filename")
    registry["order"] = list(order)
    return registry


def load_agents(project: Path) -> dict:
    meta = load_json(project / "agents.json")
    if not isinstance(meta.get("agents"), dict) or not meta["agents"]:
        raise SetupError("agents.json requires a non-empty 'agents' object")
    if not isinstance(meta.get("defaults", {}), dict):
        raise SetupError("agents.json 'defaults' must be an object")
    meta.setdefault("defaults", {})
    return meta


def resolve_root_base(project: Path, cli_value: Path | None) -> Path:
    if cli_value is not None:
        return cli_value.expanduser().resolve()
    env = os.environ.get("ARC_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return (project / "roots").resolve()


def agent_root(root_base: Path, name: str, cfg: dict) -> Path:
    root = root_base / cfg.get("dir", name)
    if not root.is_dir():
        raise SetupError(f"{name}: agent root does not exist: {root}")
    return root


# -- measured values (never typed) -------------------------------------------

def measure(project: Path, meta: dict) -> dict[str, str]:
    """Count files on disk for every entry under ``measured`` in agents.json.

    Read-only. Refuses to emit a count for a missing or empty directory, because
    a silently generated "0" is worse than a loud failure.
    """
    values: dict[str, str] = {}
    for key, spec in (meta.get("measured") or {}).items():
        directory = project / spec["dir"]
        if not directory.is_dir():
            raise SetupError(f"measured {key!r}: directory not found: {directory}")
        files = [p for p in directory.glob(spec.get("glob", "*")) if p.is_file()]
        if not files:
            raise SetupError(f"measured {key!r}: directory is empty, refusing to emit a count")
        values[f"measured.{key}"] = str(len(files))
    return values


def substitute(text: str, values: dict[str, str]) -> str:
    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key not in values:
            raise SetupError(f"unknown placeholder {{{{{key}}}}} (known: {sorted(values)})")
        return values[key]
    return _PLACEHOLDER.sub(repl, text)


# -- boot pointer ------------------------------------------------------------

def boot_pointer(name: str, root: Path, cfg: dict, defaults: dict) -> str:
    """The boot manifest this root's entry files point at, relative to the root."""
    rel = cfg.get("boot_pointer") or defaults.get("boot_pointer")
    if not rel:
        raise SetupError(f"{name}: no boot_pointer in the agent entry or in defaults")
    if not (root / rel).is_file():
        raise SetupError(f"{name}: declared boot pointer is missing: {root / rel}")
    return rel


# -- the three varying lines -------------------------------------------------

def title_line(harness: dict, title_name: str) -> str:
    return f"# {Path(harness['entry_filename']).name} → {title_name} Boot"


def entry_line(harness: dict, subject: str, lead_tail: str | None) -> str:
    line = f"**{harness['entry_point_phrase']} for {subject}.** This is a pointer."
    return f"{line} {lead_tail}" if lead_tail else line


def capability_line(harness: dict, cap: dict, scope: str, cli: bool) -> str:
    """The ONE capability line.

    Rule: registry ``capabilities.mcp == 'full'`` gets the MCP call plus the HTTP
    path; anything else (``gap`` / ``partial`` / ``none``) gets HTTP only,
    annotated as a fallback. The wording comes from ``capability_line`` in
    agents.json defaults so nothing about the query service is hard-coded here.
    """
    http = cap["http"]
    cli_part = f" · {cap['cli']}" if cli and cap.get("cli") else ""
    if harness["capabilities"].get("mcp") == "full":
        mcp = cap["mcp"]
        # Agents that also advertise the terminal CLI list all three with a dot;
        # the rest keep the two-transport "or" phrasing.
        call = f"{mcp} · {http}{cli_part}" if cli_part else f"{mcp} or {http}"
    else:
        call = f"{http} (HTTP fallback when no MCP){cli_part}"
    return cap["template"].format(scope=scope, call=call)


# -- rendering ---------------------------------------------------------------

def include_block(project: Path, spec: dict | None) -> str | None:
    """Project a block of text from a source document between two markers.

    The source document stays the single canonical copy; the generator fails
    rather than silently dropping, duplicating or mis-ordering the block.
    """
    if not spec:
        return None
    path = project / spec["file"]
    start, end = spec["start"], spec["end"]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SetupError(f"include source unavailable: {path}: {exc}") from exc
    if text.count(start) != 1 or text.count(end) != 1:
        raise SetupError(f"{path.name} requires exactly one {start!r} and one {end!r} marker")
    if text.index(end) < text.index(start):
        raise SetupError(f"{path.name} include block is reversed")
    body = text.split(start, 1)[1].split(end, 1)[0].strip()
    if not body:
        raise SetupError(f"{path.name} include block is empty")
    return body


def render_pointer(name: str, cfg: dict, defaults: dict, harness: dict, pointer: str,
                   values: dict[str, str], included: str | None) -> str:
    def value(key: str):
        return cfg[key] if key in cfg else defaults.get(key)

    cap = defaults.get("capability_line")
    if not cap or not all(k in cap for k in ("template", "mcp", "http")):
        raise SetupError("agents.json defaults need capability_line {template, mcp, http}")

    blocks: list[str] = [
        title_line(harness, cfg.get("title_name", name)),
        entry_line(harness, cfg.get("subject", name), value("lead_tail")),
    ]
    blocks.extend(cfg.get("preamble", []))
    blocks.append(f"Read [`{pointer}`]({pointer}) first. {value('boot_tail') or ''}".rstrip())
    blocks.append(capability_line(harness, cap, value("query_scope") or "", bool(cfg.get("query_cli"))))
    if included and cfg.get("include_block", True):
        blocks.append(included)
    blocks.extend(cfg.get("clauses", []))
    if value("tail_line"):
        blocks.append(value("tail_line"))
    blocks.extend(defaults.get("shared_tail", []))
    blocks.extend(cfg.get("footer", []))
    return substitute("\n\n".join(blocks), values) + "\n"


def render_verbatim(project: Path, cfg: dict) -> str:
    body_file = project / cfg["body_file"]
    try:
        return body_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise SetupError(f"verbatim body missing: {body_file} ({exc})") from exc


class Context:
    """Everything resolved once per run so render/check/apply/parity agree."""

    def __init__(self, project: Path, root_base: Path):
        self.project = project
        self.root_base = root_base
        self.registry = load_registry(project)
        self.meta = load_agents(project)
        self.order: list[str] = self.registry["order"]
        self.agents: list[str] = list(self.meta["agents"])
        defaults = self.meta["defaults"]
        harnesses = self.registry["harnesses"]
        self.values = {
            "generator": TOOL_NAME,
            "siblings": " · ".join(f"`{harnesses[h]['entry_filename']}`" for h in self.order),
            "harness_count": str(len(self.order)),
        }
        self.values.update(measure(project, self.meta))
        self.included = include_block(project, defaults.get("include"))
        # Fail fast on unresolved placeholders anywhere in shared text.
        for block in defaults.get("shared_tail", []):
            substitute(block, self.values)

    def root(self, name: str) -> Path:
        return agent_root(self.root_base, name, self.meta["agents"][name])

    def render(self, name: str) -> dict[str, str]:
        """{entry_filename: body} for one agent."""
        cfg = self.meta["agents"][name]
        harnesses = self.registry["harnesses"]
        if cfg.get("template") == "verbatim":
            body = render_verbatim(self.project, cfg)
            return {harnesses[h]["entry_filename"]: body for h in self.order}
        pointer = boot_pointer(name, self.root(name), cfg, self.meta["defaults"])
        return {
            harnesses[h]["entry_filename"]: render_pointer(
                name, cfg, self.meta["defaults"], harnesses[h], pointer,
                self.values, self.included)
            for h in self.order
        }


# -- parity proof ------------------------------------------------------------

def varying_indices(bodies: dict[str, str]) -> list[int]:
    """Line indices that are not identical across all siblings."""
    line_sets = [b.splitlines() for b in bodies.values()]
    width = max(len(ls) for ls in line_sets)
    return [
        i for i in range(width)
        if len({ls[i] if i < len(ls) else None for ls in line_sets}) > 1
    ]


def invariant_digest(body: str, skip: set[int]) -> str:
    kept = [ln for i, ln in enumerate(body.splitlines()) if i not in skip]
    return hashlib.sha256("\n".join(kept).encode("utf-8")).hexdigest()[:16]


def parity_report(name: str, bodies: dict[str, str]) -> tuple[bool, list[str]]:
    varying = varying_indices(bodies)
    digests = {fn: invariant_digest(b, set(varying)) for fn, b in bodies.items()}
    identical = len(set(digests.values())) == 1
    # A pointer agent varies on exactly 3 lines; a verbatim agent on 0.
    ok = identical and len(varying) in (0, 3)
    lines = [
        f"{name:<20} varying_lines={len(varying)} "
        f"invariant_digest={'IDENTICAL' if identical else 'DIVERGED'} "
        f"{'OK' if ok else 'FAIL'}"
    ]
    for fn in sorted(digests):
        lines.append(f"    {fn:<16} {digests[fn]}  ({len(bodies[fn])} bytes)")
    return ok, lines


# -- modes -------------------------------------------------------------------

def check(ctx: Context, targets: list[str], show_diff: bool) -> int:
    bad: list[str] = []
    n_bad = 0
    for name in targets:
        home = ctx.root(name)
        for filename, want in ctx.render(name).items():
            path = home / filename
            try:
                have = path.read_text(encoding="utf-8")
            except FileNotFoundError:
                bad.append(f"MISSING    {path}")
                n_bad += 1
                continue
            except OSError as exc:
                bad.append(f"UNREADABLE {path}: {exc}")
                n_bad += 1
                continue
            if have != want:
                bad.append(f"DIFFERS    {path}")
                n_bad += 1
                if show_diff:
                    for ln in difflib.unified_diff(
                            have.splitlines(), want.splitlines(),
                            fromfile=f"{path} (on disk)", tofile=f"{path} (generated)",
                            lineterm="", n=1):
                        bad.append(f"    {ln}")
    if bad:
        print(f"{TOOL_NAME} --check: FAIL")
        print("\n".join(bad))
        print(f"\n{n_bad} file(s) out of parity.")
        return 1
    total = len(ctx.order) * len(targets)
    print(f"{TOOL_NAME} --check: PASS - {total} files across {len(targets)} agents "
          "match the generated source.")
    return 0


def apply(ctx: Context, targets: list[str], stage: Path | None) -> int:
    written = unchanged = 0
    for name in targets:
        dest_root = (stage / name) if stage else ctx.root(name)
        dest_root.mkdir(parents=True, exist_ok=True)
        for filename, body in ctx.render(name).items():
            path = dest_root / filename
            if path.exists() and path.read_text(encoding="utf-8") == body:
                unchanged += 1
                continue
            path.write_text(body, encoding="utf-8")
            written += 1
            print(f"{'staged' if stage else 'wrote'}  {path}")
    print(f"\n{TOOL_NAME} --{'stage' if stage else 'apply'}: "
          f"{written} written, {unchanged} already current.")
    return 0


def parity(ctx: Context, targets: list[str], on_disk: bool) -> int:
    source = "files on disk" if on_disk else "generated output"
    print(f"Hashing {source}; the permitted varying lines are removed, "
          f"so all {len(ctx.order)} siblings must match.\n")
    failed = False
    for name in targets:
        if on_disk:
            home = ctx.root(name)
            bodies = {}
            for filename in ctx.render(name):
                try:
                    bodies[filename] = (home / filename).read_text(encoding="utf-8")
                except OSError as exc:
                    print(f"{name:<20} MISSING {filename}: {exc}")
                    failed = True
            if len(bodies) != len(ctx.order):
                continue
        else:
            bodies = ctx.render(name)
        ok, lines = parity_report(name, bodies)
        failed = failed or not ok
        print("\n".join(lines))
    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", type=Path, default=Path("examples/basic"), metavar="DIR",
                    help="directory holding registry.json and agents.json "
                         "(default: examples/basic)")
    ap.add_argument("--root-base", type=Path, metavar="DIR",
                    help="parent of the agent roots (default: $ARC_ROOT, else <project>/roots)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true",
                      help="compare on-disk to generated; exit 1 on any difference (default)")
    mode.add_argument("--apply", action="store_true", help="write the generated files")
    mode.add_argument("--parity", action="store_true",
                      help="hash each body modulo the three permitted varying lines")
    ap.add_argument("--stage", type=Path, metavar="DIR",
                    help="with --apply, render into DIR/<agent>/ instead of the live root")
    ap.add_argument("--on-disk", action="store_true",
                    help="with --parity, hash the files that exist instead of the generated text")
    ap.add_argument("--agent", action="append", metavar="NAME",
                    help="scope to one agent (repeatable)")
    ap.add_argument("--diff", action="store_true", help="with --check, print unified diffs")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project = args.project.expanduser().resolve()
        ctx = Context(project, resolve_root_base(project, args.root_base))
        targets = ctx.agents
        if args.agent:
            unknown = [a for a in args.agent if a not in ctx.agents]
            if unknown:
                raise SetupError(f"unknown agent(s) {unknown}; known: {ctx.agents}")
            targets = [a for a in ctx.agents if a in set(args.agent)]
        if args.apply:
            return apply(ctx, targets, args.stage)
        if args.parity:
            return parity(ctx, targets, args.on_disk)
        return check(ctx, targets, args.diff)
    except SetupError as exc:
        print(f"{TOOL_NAME}: setup error - {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
