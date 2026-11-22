from types import SimpleNamespace
from unittest.mock import patch

from agents.creative_director.agent import (
    guard_quality_gate,
    check_specialist_response,
    record_critic_verdict,
    SPECIALIST_FAILURE,
    GATE_APPROVED,
    GATE_ROUNDS,
    GATE_EXHAUSTED,
    MAX_CRITIC_ROUNDS,
)


def context(**state):
    return SimpleNamespace(state=state)


def tool(name):
    return SimpleNamespace(name=name)


def approved_verdict():
    return """
**POSTS REVIEW:**
- Status: APPROVED

**VISUALS REVIEW:**
- Status: APPROVED

**OVERALL ASSESSMENT:**
- All Approved: YES
"""


def rejected_verdict():
    return """
**POSTS REVIEW:**
- Status: NEEDS_REVISION

**VISUALS REVIEW:**
- Status: NEEDS_REVISION

**OVERALL ASSESSMENT:**
- All Approved: NO
"""


def test_pm_blocked_without_approval():
    ctx = context(active_campaign=True)

    result = guard_quality_gate(tool("project_manager"), {}, ctx)

    assert result["status"] == "blocked"


def test_pm_allowed_after_approval():
    ctx = context(active_campaign=True, **{GATE_APPROVED: True})

    result = guard_quality_gate(tool("project_manager"), {}, ctx)

    assert result is None


def test_copywriter_error_blocks_dependent_designer():
    ctx = context(active_campaign=True)

    with patch(
        "agents.creative_director.agent.AgentTool",
        SimpleNamespace,
    ):
        failure = check_specialist_response(
            tool("copywriter"),
            {},
            ctx,
            {"error": "Copywriter service unavailable"},
        )

    assert failure["status"] == "error"
    assert failure["error_message"] == "Copywriter service unavailable"
    assert ctx.state[SPECIALIST_FAILURE] == {
        "agent": "copywriter",
        "error_message": "Copywriter service unavailable",
    }

    blocked = guard_quality_gate(tool("designer"), {}, ctx)

    assert blocked["status"] == "blocked"
    assert blocked["error_message"] == "Copywriter service unavailable"
    with patch(
        "agents.creative_director.agent.AgentTool",
        SimpleNamespace,
    ):
        assert check_specialist_response(
            tool("designer"), {}, ctx, ""
        ) is None
    assert ctx.state[SPECIALIST_FAILURE]["agent"] == "copywriter"


def test_rejected_critic_verdict():
    ctx = context(active_campaign=True)

    result = record_critic_verdict(
        tool("critic"), ctx, rejected_verdict()
    )

    assert result is None
    assert ctx.state[GATE_APPROVED] is False
    assert ctx.state[GATE_ROUNDS] == 1


def test_approved_critic_verdict():
    ctx = context(active_campaign=True)

    result = record_critic_verdict(
        tool("critic"), ctx, approved_verdict()
    )

    assert result is None
    assert ctx.state[GATE_APPROVED] is True
    assert ctx.state[GATE_ROUNDS] == 1


def test_maximum_review_rounds():
    ctx = context(active_campaign=True)

    for _ in range(MAX_CRITIC_ROUNDS):
        result = record_critic_verdict(
            tool("critic"), ctx, rejected_verdict()
        )

    assert result["status"] == "rejected"
    assert ctx.state[GATE_ROUNDS] == MAX_CRITIC_ROUNDS
    assert ctx.state[GATE_EXHAUSTED] is True

    blocked = guard_quality_gate(tool("critic"), {}, ctx)
    assert blocked["status"] == "blocked"

    blocked_pm = guard_quality_gate(
        tool("project_manager"), {}, ctx
    )
    assert blocked_pm["status"] == "blocked"


def test_blocked_critic_callback_does_not_increment_rounds():
    ctx = context(active_campaign=True, **{GATE_ROUNDS: MAX_CRITIC_ROUNDS})
    critic = tool("critic")

    blocked = guard_quality_gate(critic, {}, ctx)
    assert blocked["status"] == "blocked"

    with patch(
        "agents.creative_director.agent.AgentTool",
        SimpleNamespace,
    ):
        result = check_specialist_response(critic, {}, ctx, blocked)

    assert result is None
    assert ctx.state[GATE_ROUNDS] == MAX_CRITIC_ROUNDS
    assert ctx.state.get(SPECIALIST_FAILURE) is None


def test_critic_blocked_without_campaign():
    ctx = context()

    result = guard_quality_gate(tool("critic"), {}, ctx)

    assert result["status"] == "blocked"


def test_pm_blocked_without_campaign():
    ctx = context()

    result = guard_quality_gate(tool("project_manager"), {}, ctx)

    assert result["status"] == "blocked"
