"""Tier 3 reads, and the control that asserts the dangerous parameters stay ABSENT.

*A control nobody has seen fail is a hypothesis.* The absence of a `force`
parameter is the load-bearing property of this whole design — it is what lets the
installed hooks be a real backstop rather than an honour system — and absence is
exactly the kind of property that decays silently when someone later adds a
convenience flag. So it is asserted, not assumed.
"""

import inspect

import pytest

from core import tiers
from core.engine import GitRobot
from core.errors import RefusalError, UsageError


# -- Tier 3: cheap, always available, allow-listed ----------------------------

@pytest.mark.parametrize("op,args", [
    ("status", []),
    ("status", ["--porcelain"]),
    ("log", ["-3", "--oneline"]),
    ("diff", []),
    ("show", ["HEAD"]),
    ("ls-files", []),
    ("rev-parse", ["HEAD"]),
    ("branch", ["--list"]),
    ("remote", ["-v"]),
    ("worktree", ["list"]),
    ("describe", ["--always"]),
])
def test_allow_listed_reads_pass_through(robot, op, args):
    assert robot.read(op, args)["ok"]


@pytest.mark.parametrize("op,args", [
    ("branch", ["-D", "illustrated"]),
    ("branch", ["-d", "illustrated"]),
    ("tag", ["-d", "v1"]),
    ("config", ["user.email", "x@y"]),
    ("remote", ["remove", "origin"]),
    ("worktree", ["prune"]),
    ("stash", ["pop"]),
])
def test_mutating_forms_of_read_subcommands_are_refused(robot, op, args):
    """`branch --list` reads; `branch -D` deletes. Splitting by subcommand alone
    would have let the second through."""
    with pytest.raises(RefusalError):
        robot.read(op, args)


@pytest.mark.parametrize("op", ["push", "commit", "merge", "rebase", "reset",
                                "clean", "checkout", "fetch", "pull", "gc",
                                "filter-branch", "update-ref", "reflog"])
def test_unclassified_operations_are_refused_not_passed_through(robot, op):
    """The allow-list inversion: everything nobody has classified yet is refused.

    An enumerated deny-list permits every subcommand not yet thought of, which is
    the defect this replaces."""
    with pytest.raises(RefusalError):
        robot.read(op, [])


@pytest.mark.parametrize("flag", [
    "-c", "--git-dir", "--work-tree", "--exec-path", "-C",
    "--git-dir=/elsewhere", "--work-tree=/elsewhere",
])
def test_redirect_flags_are_refused_even_on_reads(robot, flag):
    """A 'read' pointed at another checkout is not a read of the guarded tree —
    and `-c core.hooksPath=` would disable the layer gitRobot protects."""
    with pytest.raises(RefusalError):
        robot.read("status", [flag])


def test_a_subcommand_string_with_arguments_is_rejected(robot):
    """read(op='status --porcelain') would slip its flags past the allow-list check."""
    with pytest.raises(UsageError, match="separately"):
        robot.read("status --porcelain")


def test_status_reports_what_would_block_a_push(robot):
    result = robot.status()
    assert result["preflight_ok"] is False
    assert any("preflight" in b for b in result["would_block_push"])
    assert any("gate pipeline is missing" in b for b in result["would_block_push"])


def test_reads_work_with_no_gate_pipeline_present(robot):
    """A blind agent makes worse decisions, not safer ones — reads must never
    depend on the gate, the preflight, or anything but a subprocess call."""
    assert robot.read("status")["ok"]
    assert robot.read("log", ["-1"])["ok"]


# -- the absent-parameter control ---------------------------------------------

FORBIDDEN_PARAMS = {"force", "no_verify", "skip_gates", "allow_dirty", "repo",
                    "cmd", "command", "passthrough", "argv", "shell", "hooks_path"}

PUBLIC_METHODS = ["read", "status", "stage", "commit", "preflight", "push",
                  "worktree", "explain", "history"]


@pytest.mark.parametrize("name", PUBLIC_METHODS)
def test_no_public_method_accepts_a_bypass_parameter(name):
    params = set(inspect.signature(getattr(GitRobot, name)).parameters) - {"self"}
    leaked = params & FORBIDDEN_PARAMS
    assert not leaked, (
        f"GitRobot.{name} gained {sorted(leaked)}. These parameters are absent BY DESIGN: "
        f"they are what makes the installed hooks a real backstop instead of an honour "
        f"system. If one is genuinely needed, that is a design change, not a convenience."
    )


def test_the_mcp_surface_has_no_bypass_parameter_either():
    """The tool surface is the part an agent can actually reach."""
    pytest.importorskip("mcp")
    from gitrobot_server import server

    # Every REGISTERED tool, taken from the tool manager rather than a hand-kept
    # list — a bypass parameter added on a new tool has to be caught too.
    tools = server.mcp._tool_manager._tools
    assert len(tools) >= 9, "tool registry looks empty — the introspection broke"
    for name, tool in sorted(tools.items()):
        params = set(inspect.signature(tool.fn).parameters)
        assert not (params & FORBIDDEN_PARAMS), f"MCP tool {name} exposes a bypass parameter"


def test_there_is_no_raw_passthrough_tool():
    pytest.importorskip("mcp")
    from gitrobot_server import server

    for banned in ("passthrough", "run", "git", "exec", "raw", "shell"):
        assert not hasattr(server, banned), (
            f"a {banned!r} tool would make every tier classification decorative")


def test_gate_disabling_flags_are_never_synthesised():
    """gitRobot must not pass --no-verify/--force itself, whatever a caller does."""
    import core.engine as engine
    import core.gitio as gitio

    source = inspect.getsource(engine) + inspect.getsource(gitio)
    for flag in ("--no-verify", "--force-with-lease", "core.hooksPath"):
        # allowed to be MENTIONED in prose/comments, never inside an argv list
        for line in source.splitlines():
            stripped = line.strip()
            if flag in line and not stripped.startswith("#") and '"' + flag + '"' in line:
                pytest.fail(f"{flag} appears in an argv position: {line.strip()}")


def test_the_forbidden_flag_table_covers_the_known_bypasses():
    for flag in ("--no-verify", "--force", "-f"):
        assert flag in tiers.FORBIDDEN_FLAGS
    for flag in ("-c", "--git-dir", "--work-tree", "--exec-path"):
        assert flag in tiers.FORBIDDEN_GLOBALS


# -- history + explain --------------------------------------------------------

def test_history_returns_the_log(robot, dirty):
    with pytest.raises(RefusalError):
        robot.guard_tier1("clean", ["-fd"])
    result = robot.history(limit=5)
    assert result["count"] == 1 and result["records"][0]["op"] == "clean"


def test_explain_on_an_unknown_id_is_a_usage_error(robot):
    with pytest.raises(UsageError, match="no refusal with id"):
        robot.explain("deadbeef")
