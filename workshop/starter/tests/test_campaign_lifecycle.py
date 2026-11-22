
from types import SimpleNamespace

from agents.creative_director.agent import (
    start_campaign,
    guard_quality_gate,
    GATE_ROUNDS,
    GATE_APPROVED,
    GATE_EXHAUSTED,
    SPECIALIST_FAILURE,
)

from agents.creative_director.agent import (
    start_campaign,
    guard_quality_gate,
    record_critic_verdict,
    GATE_ROUNDS,
    GATE_APPROVED,
    GATE_EXHAUSTED,
)

def make_context():
    return SimpleNamespace(state={})


def test_campaign_initialization():
    ctx = make_context()

    result = start_campaign("GreenBrew Campaign", ctx)

    assert result["status"] == "success"
    assert ctx.state["active_campaign"] == "GreenBrew Campaign"
    assert ctx.state[GATE_ROUNDS] == 0
    assert ctx.state[GATE_APPROVED] is False
    assert ctx.state[GATE_EXHAUSTED] is False


def test_empty_campaign_name():
    ctx = make_context()

    result = start_campaign("   ", ctx)

    assert result["status"] == "error"
    assert "active_campaign" not in ctx.state


def test_duplicate_campaign_blocked():
    ctx = make_context()

    start_campaign("Campaign One", ctx)
    result = start_campaign("Campaign Two", ctx)

    assert result["status"] == "blocked"
    assert ctx.state["active_campaign"] == "Campaign One"


def test_failure_flag_resets_only_for_new_campaign():
    ctx = make_context()
    prior_failure = {
        "agent": "copywriter",
        "error_message": "Service unavailable",
    }
    ctx.state[SPECIALIST_FAILURE] = prior_failure.copy()

    started = start_campaign("Campaign One", ctx)

    assert started["status"] == "success"
    assert ctx.state[SPECIALIST_FAILURE] is None

    ctx.state[SPECIALIST_FAILURE] = prior_failure.copy()
    duplicate = start_campaign("Campaign Two", ctx)

    assert duplicate["status"] == "blocked"
    assert ctx.state[SPECIALIST_FAILURE] == prior_failure


def test_campaign_blocks_pm_before_approval():
    ctx = make_context()
    start_campaign("GreenBrew Campaign", ctx)

    pm_tool = SimpleNamespace(name="project_manager")

    result = guard_quality_gate(pm_tool, {}, ctx)

    assert result is not None
    assert result["status"] == "blocked"


def test_campaign_approval_workflow():
    ctx = make_context()

    # Step 1: Start a new campaign
    result = start_campaign("GreenBrew Campaign", ctx)
    assert result["status"] == "success"

    pm_tool = SimpleNamespace(name="project_manager")
    critic_tool = SimpleNamespace(name="critic")

    # Step 2: PM must be blocked before approval
    blocked = guard_quality_gate(pm_tool, {}, ctx)
    assert blocked is not None
    assert blocked["status"] == "blocked"

    # Step 3: Critic approves both posts and visuals
    critic_response = {
        "result": """
**POSTS REVIEW:**
- Status: APPROVED

**VISUALS REVIEW:**
- Status: APPROVED

**OVERALL ASSESSMENT:**
- All Approved: YES
"""
    }

    record_critic_verdict(critic_tool, ctx, critic_response)

    # Step 4: Verify approval state
    assert ctx.state[GATE_ROUNDS] == 1
    assert ctx.state[GATE_APPROVED] is True

    # Step 5: PM should now be allowed
    allowed = guard_quality_gate(pm_tool, {}, ctx)
    assert allowed is None


def test_campaign_rejected_after_three_reviews():
    ctx = make_context()
    start_campaign("Rejected Campaign", ctx)

    critic_tool = SimpleNamespace(name="critic")
    pm_tool = SimpleNamespace(name="project_manager")

    rejected_response = {
        "result": """
**POSTS REVIEW:**
- Status: NEEDS_REVISION

**VISUALS REVIEW:**
- Status: NEEDS_REVISION

**OVERALL ASSESSMENT:**
- All Approved: NO
"""
    }

    # Three rejected Critic reviews
    for round_number in range(1, 4):
        assert guard_quality_gate(critic_tool, {}, ctx) is None

        record_critic_verdict(
            critic_tool,
            ctx,
            rejected_response,
        )

        assert ctx.state[GATE_ROUNDS] == round_number
        assert ctx.state[GATE_APPROVED] is False

    # Revision/review limit reached
    assert ctx.state[GATE_EXHAUSTED] is True

    # A fourth Critic review must be blocked
    blocked_critic = guard_quality_gate(
        critic_tool, {}, ctx
    )

    assert blocked_critic is not None
    assert blocked_critic["status"] == "blocked"

    # Project Manager must remain blocked
    blocked_pm = guard_quality_gate(
        pm_tool, {}, ctx
    )

    assert blocked_pm is not None
    assert blocked_pm["status"] == "blocked"
