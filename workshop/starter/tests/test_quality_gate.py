import importlib.util
from pathlib import Path

import pytest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "agents"
    / "creative_director"
    / "agent.py"
)


def load_approval_parser():
    """Load the pure parser without initializing ADK or cloud clients."""
    import ast

    source = ast.parse(SOURCE.read_text(encoding="utf-8"))
    parser = next(
        node for node in source.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "parse_critic_approval"
    )

    module = ast.Module(body=[parser], type_ignores=[])
    namespace = {"re": __import__("re")}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace["parse_critic_approval"]


parse_critic_approval = load_approval_parser()


def verdict(posts="APPROVED", visuals="APPROVED", overall="YES"):
    return f"""
**POSTS REVIEW:**
- Status: {posts}

**VISUALS REVIEW:**
- Status: {visuals}

**OVERALL ASSESSMENT:**
- All Approved: {overall}
"""


@pytest.mark.parametrize(
    "response, expected",
    [
        (verdict(), True),
        (verdict(posts="NEEDS_REVISION"), False),
        (verdict(visuals="NEEDS_REVISION"), False),
        (verdict(overall="NO"), False),
        (verdict(posts="NEEDS_REVISION", overall="YES"), False),
        ("Everything looks good!", False),
        ("", False),
        (verdict(visuals="NOT_REVIEWED"), False),
    ],
)
def test_critic_approval(response, expected):
    assert parse_critic_approval(response) is expected


def test_duplicate_approval_field_is_rejected():
    response = verdict() + "\n- All Approved: YES\n"
    assert parse_critic_approval(response) is False
