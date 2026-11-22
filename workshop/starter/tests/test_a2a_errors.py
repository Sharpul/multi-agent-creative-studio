
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.creative_director.agent import (
    check_specialist_response,
    guard_quality_gate,
    GATE_APPROVED,
    GATE_ROUNDS,
)


@pytest.mark.parametrize(
    "response, expected_error",
    [
        ("", "empty response"),
        ("   ", "empty response"),
        ({"error": "Service unavailable"}, "Service unavailable"),
        ({"error_message": "Request timed out"}, "Request timed out"),
    ],
)
def test_specialist_errors(response, expected_error):
    fake_tool = SimpleNamespace(name="copywriter")

    with patch(
        "agents.creative_director.agent.AgentTool",
        SimpleNamespace,
    ):
        result = check_specialist_response(
            fake_tool, {}, SimpleNamespace(state={}), response
        )

    assert result["status"] == "error"
    assert expected_error in result["error_message"]
    assert "Do not proceed" in result["instruction"]


def test_successful_specialist_response():
    fake_tool = SimpleNamespace(name="copywriter")

    with patch(
        "agents.creative_director.agent.AgentTool",
        SimpleNamespace,
    ):
        result = check_specialist_response(
            fake_tool,
            {},
            SimpleNamespace(state={}),
            {"result": "Three captions generated"},
        )

    assert result is None


def test_critic_transport_error_does_not_count_as_review():
    fake_tool = SimpleNamespace(name="critic")
    ctx = SimpleNamespace(state={"active_campaign": "Offline campaign"})

    with patch(
        "agents.creative_director.agent.AgentTool",
        SimpleNamespace,
    ):
        result = check_specialist_response(
            fake_tool,
            {},
            ctx,
            {"error": "Critic transport timed out"},
        )

    assert result["status"] == "error"
    assert result["error_message"] == "Critic transport timed out"
    assert ctx.state.get(GATE_ROUNDS, 0) == 0
    assert ctx.state.get(GATE_APPROVED, False) is False
    assert guard_quality_gate(fake_tool, {}, ctx)["status"] == "blocked"
