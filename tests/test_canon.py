"""Tests for cross_harness_canon. Stdlib only: ``python3 -m unittest discover -s tests -v``."""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXAMPLE = REPO / "examples" / "basic"

spec = importlib.util.spec_from_file_location("canon", REPO / "cross_harness_canon.py")
canon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canon)

SIBLINGS = ["CLAUDE.md", "AGENTS.md", "HERMES.md", "GEMINI.md", "ANTIGRAVITY.md"]


def run(*argv):
    """Run main() in-process, returning (exit_code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = canon.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class Workspace(unittest.TestCase):
    """Each test gets a private copy of the example project."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name) / "proj"
        # Copy the inputs only; the committed generated files are not part of the fixture.
        shutil.copytree(EXAMPLE, self.project, ignore=shutil.ignore_patterns(*SIBLINGS))
        self.args = ["--project", str(self.project)]

    def edit_json(self, name, fn):
        path = self.project / name
        data = json.loads(path.read_text())
        fn(data)
        path.write_text(json.dumps(data, indent=2))

    def ctx(self):
        return canon.Context(self.project, self.project / "roots")


class RenderTests(Workspace):
    def test_every_agent_gets_one_file_per_harness(self):
        ctx = self.ctx()
        for name in ctx.agents:
            self.assertEqual(sorted(SIBLINGS), sorted(ctx.render(name)), name)

    def test_pointer_agents_vary_on_exactly_three_lines(self):
        ctx = self.ctx()
        for name in ("example-agent", "researcher", "reviewer"):
            bodies = ctx.render(name)
            self.assertEqual(3, len(canon.varying_indices(bodies)), name)
            self.assertTrue(canon.parity_report(name, bodies)[0], name)

    def test_verbatim_agent_varies_on_zero_lines(self):
        bodies = self.ctx().render("shared-notes")
        self.assertEqual([], canon.varying_indices(bodies))
        self.assertEqual(1, len(set(bodies.values())))

    def test_the_three_varying_lines_are_title_entry_and_capability(self):
        bodies = self.ctx().render("example-agent")
        lines = {fn: b.splitlines() for fn, b in bodies.items()}
        varying = canon.varying_indices(bodies)
        self.assertEqual([0, 2, 6], varying)
        self.assertEqual("# CLAUDE.md → example-agent Boot", lines["CLAUDE.md"][0])
        self.assertIn("Codex / generic agent platforms entry point", lines["AGENTS.md"][2])

    def test_capability_line_follows_registry_mcp_value(self):
        bodies = self.ctx().render("example-agent")
        self.assertIn("(MCP)", bodies["GEMINI.md"])
        self.assertNotIn("HTTP fallback", bodies["GEMINI.md"])
        self.assertIn("(HTTP fallback when no MCP)", bodies["ANTIGRAVITY.md"])
        self.assertNotIn("(MCP)", bodies["ANTIGRAVITY.md"])

    def test_flipping_a_registry_capability_changes_only_that_harness(self):
        before = self.ctx().render("researcher")
        self.edit_json("registry.json",
                       lambda d: d["harnesses"]["gemini_cli"]["capabilities"].update(mcp="none"))
        after = self.ctx().render("researcher")
        self.assertNotEqual(before["GEMINI.md"], after["GEMINI.md"])
        for fn in set(SIBLINGS) - {"GEMINI.md"}:
            self.assertEqual(before[fn], after[fn], fn)

    def test_cli_flag_adds_third_transport_only_when_requested(self):
        bodies = self.ctx().render("researcher")
        self.assertIn('kb-query "..."', bodies["CLAUDE.md"])
        self.assertNotIn("kb-query", self.ctx().render("example-agent")["CLAUDE.md"])

    def test_per_agent_clause_reaches_all_five_files(self):
        for fn, body in self.ctx().render("reviewer").items():
            self.assertIn("Review notes are private", body, fn)

    def test_measured_count_matches_files_on_disk(self):
        body = self.ctx().render("example-agent")["CLAUDE.md"]
        self.assertIn("the 3 project rules", body)
        (self.project / "rules" / "004_extra.md").write_text("# Rule 004\n")
        self.assertIn("the 4 project rules", self.ctx().render("example-agent")["CLAUDE.md"])

    def test_included_block_is_projected_once_and_can_be_opted_out(self):
        bodies = self.ctx().render("example-agent")
        for fn, body in bodies.items():
            self.assertEqual(1, body.count("**Review contract:**"), fn)
        for body in self.ctx().render("reviewer").values():
            self.assertNotIn("**Review contract:**", body)


class SetupErrorTests(Workspace):
    def test_missing_boot_pointer_is_a_setup_error(self):
        (self.project / "roots" / "researcher" / "boot" / "home.md").unlink()
        code, _, err = run(*self.args, "--check")
        self.assertEqual(2, code)
        self.assertIn("boot pointer is missing", err)

    def test_missing_agent_root_is_a_setup_error(self):
        shutil.rmtree(self.project / "roots" / "reviewer")
        self.assertEqual(2, run(*self.args, "--check")[0])

    def test_unknown_harness_in_order_is_rejected(self):
        self.edit_json("registry.json", lambda d: d["order"].append("nope"))
        self.assertEqual(2, run(*self.args, "--check")[0])

    def test_harness_missing_from_order_is_rejected_not_silently_dropped(self):
        self.edit_json("registry.json", lambda d: d["order"].remove("hermes"))
        code, _, err = run(*self.args, "--check")
        self.assertEqual(2, code)
        self.assertIn("hermes", err)

    def test_duplicate_entry_filename_is_rejected(self):
        self.edit_json("registry.json",
                       lambda d: d["harnesses"]["codex"].update(entry_filename="CLAUDE.md"))
        self.assertEqual(2, run(*self.args, "--check")[0])

    def test_empty_measured_directory_refuses_to_emit_a_count(self):
        for p in (self.project / "rules").glob("[0-9]*_*.md"):
            p.unlink()
        code, _, err = run(*self.args, "--check")
        self.assertEqual(2, code)
        self.assertIn("refusing to emit a count", err)

    def test_unknown_placeholder_fails_generation(self):
        self.edit_json("agents.json",
                       lambda d: d["defaults"]["shared_tail"].append("{{not.a.thing}}"))
        code, _, err = run(*self.args, "--check")
        self.assertEqual(2, code)
        self.assertIn("unknown placeholder", err)

    def test_missing_or_duplicate_include_markers_fail_generation(self):
        card = self.project / "rules" / "operating-card.md"
        start, end = "<!-- review-contract:start -->", "<!-- review-contract:end -->"
        for content in ("no contract", f"{start}{start}{end}", f"{end}x{start}", f"{start}{end}"):
            card.write_text(content)
            self.assertEqual(2, run(*self.args, "--check")[0], content)

    def test_unknown_agent_scope_is_a_setup_error(self):
        self.assertEqual(2, run(*self.args, "--check", "--agent", "ghost")[0])

    def test_unreadable_registry_is_a_setup_error(self):
        (self.project / "registry.json").write_text("{not json")
        self.assertEqual(2, run(*self.args, "--check")[0])


class DriftTests(Workspace):
    def setUp(self):
        super().setUp()
        self.assertEqual(0, run(*self.args, "--apply")[0])
        self.victim = (self.project / "roots" / "researcher" / "AGENTS.md").resolve()

    def test_clean_tree_passes(self):
        code, out, _ = run(*self.args, "--check")
        self.assertEqual(0, code)
        self.assertIn("PASS - 20 files", out)

    def test_hand_edit_is_detected(self):
        self.victim.write_text(self.victim.read_text() + "\nA rule that only Codex sees.\n")
        code, out, _ = run(*self.args, "--check")
        self.assertEqual(1, code)
        self.assertIn(f"DIFFERS    {self.victim}", out)

    def test_diff_flag_shows_the_offending_line(self):
        self.victim.write_text(self.victim.read_text() + "\nsneaky line\n")
        _, out, _ = run(*self.args, "--check", "--diff")
        self.assertIn("-sneaky line", out)

    def test_missing_file_is_detected(self):
        self.victim.unlink()
        code, out, _ = run(*self.args, "--check")
        self.assertEqual(1, code)
        self.assertIn("MISSING", out)

    def test_stale_output_after_canonical_change_is_detected(self):
        self.edit_json("agents.json",
                       lambda d: d["defaults"].update(lead_tail="A changed canonical sentence."))
        self.assertEqual(1, run(*self.args, "--check")[0])

    def test_apply_repairs_drift_and_is_idempotent(self):
        self.victim.write_text("garbage")
        self.assertEqual(1, run(*self.args, "--check")[0])
        code, out, _ = run(*self.args, "--apply")
        self.assertEqual(0, code)
        self.assertIn("1 written, 19 already current", out)
        self.assertEqual(0, run(*self.args, "--check")[0])
        self.assertIn("0 written, 20 already current", run(*self.args, "--apply")[1])

    def test_agent_scope_limits_what_is_checked(self):
        self.victim.write_text("garbage")
        self.assertEqual(0, run(*self.args, "--check", "--agent", "reviewer")[0])
        self.assertEqual(1, run(*self.args, "--check", "--agent", "researcher")[0])

    def test_on_disk_parity_catches_a_fourth_varying_line(self):
        self.assertEqual(0, run(*self.args, "--parity", "--on-disk")[0])
        self.victim.write_text(self.victim.read_text().replace("read on demand", "read eagerly"))
        code, out, _ = run(*self.args, "--parity", "--on-disk")
        self.assertEqual(1, code)
        # A fourth varying line is exactly the illegal drift the invariant forbids.
        self.assertIn("varying_lines=4", out)
        self.assertIn("FAIL", out)


class ModeTests(Workspace):
    def test_stage_renders_elsewhere_and_leaves_the_live_root_untouched(self):
        stage = Path(self._tmp.name) / "stage"
        code, _, _ = run(*self.args, "--apply", "--stage", str(stage))
        self.assertEqual(0, code)
        self.assertTrue((stage / "researcher" / "CLAUDE.md").is_file())
        self.assertFalse((self.project / "roots" / "researcher" / "CLAUDE.md").exists())

    def test_root_base_flag_and_env_var_relocate_the_roots(self):
        other = Path(self._tmp.name) / "elsewhere"
        shutil.copytree(self.project / "roots", other)
        self.assertEqual(0, run(*self.args, "--root-base", str(other), "--apply")[0])
        self.assertTrue((other / "researcher" / "GEMINI.md").is_file())
        os.environ["ARC_ROOT"] = str(other)
        self.addCleanup(os.environ.pop, "ARC_ROOT", None)
        self.assertEqual(0, run(*self.args, "--check")[0])

    def test_check_is_the_default_mode(self):
        self.assertEqual(1, run(*self.args)[0])  # nothing applied yet in this copy
        run(*self.args, "--apply")
        self.assertEqual(0, run(*self.args)[0])

    def test_cli_exit_codes_via_subprocess(self):
        cmd = [sys.executable, str(REPO / "cross_harness_canon.py"), *self.args]
        self.assertEqual(1, subprocess.run(cmd + ["--check"], capture_output=True).returncode)
        self.assertEqual(0, subprocess.run(cmd + ["--apply"], capture_output=True).returncode)
        self.assertEqual(0, subprocess.run(cmd + ["--check"], capture_output=True).returncode)
        (self.project / "registry.json").write_text("[]")
        self.assertEqual(2, subprocess.run(cmd + ["--check"], capture_output=True).returncode)


class CommittedExampleTests(unittest.TestCase):
    """The generated files committed under examples/ must never drift (CI gate)."""

    def test_committed_example_outputs_match_the_generator(self):
        code, out, err = run("--project", str(EXAMPLE), "--root-base", str(EXAMPLE / "roots"), "--check")
        self.assertEqual(0, code, out + err)


if __name__ == "__main__":
    unittest.main()
