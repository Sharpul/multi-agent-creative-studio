"""Offline characterization of Creative Director callbacks and fixture flows."""
import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

URL_KEYS = (
    "COPYWRITER_AGENT_URL",
    "DESIGNER_AGENT_URL",
    "STRATEGIST_AGENT_URL",
    "CRITIC_AGENT_URL",
    "PM_AGENT_URL",
)


def summarize(states):
    """Summarize only gate values actually recorded in supplied states."""
    approval_values = [
        state["quality_gate_approved"]
        for state in states
        if isinstance(state.get("quality_gate_approved"), bool)
    ]
    review_values = [
        state["quality_gate_rounds"]
        for state in states
        if isinstance(state.get("quality_gate_rounds"), int)
        and not isinstance(state.get("quality_gate_rounds"), bool)
    ]
    exhausted_values = [
        state["quality_gate_exhausted"]
        for state in states
        if isinstance(state.get("quality_gate_exhausted"), bool)
    ]
    return {
        "state_count": len(states),
        "critic_approval_rate": (
            sum(approval_values) / len(approval_values)
            if approval_values else None
        ),
        "critic_approval_observation_count": len(approval_values),
        "total_critic_reviews": sum(review_values) if review_values else None,
        "average_critic_review_count": (
            sum(review_values) / len(review_values)
            if review_values else None
        ),
        "critic_review_observation_count": len(review_values),
        "review_exhaustion_count": (
            sum(exhausted_values) if exhausted_values else None
        ),
        "review_exhaustion_observation_count": len(exhausted_values),
        "campaign_completion_success_rate": None,
        "campaign_completion_metric_note": (
            "Unavailable: these callbacks do not record completed outputs "
            "or campaign completion."
        ),
        "specialist_failure_rate": None,
        "specialist_failure_metric_note": (
            "Unavailable: the callbacks retain a failure flag but do not "
            "record specialist invocation totals."
        ),
        "specialist_latency": None,
        "specialist_latency_metric_note": (
            "Unavailable: the restored callbacks do not record latency."
        ),
    }


def run_fixtures(cases):
    """Run fixture-planned calls through the real callbacks, without remotes."""
    previous_dotenv_disabled = os.environ.get("PYTHON_DOTENV_DISABLED")
    previous_urls = {key: os.environ.get(key) for key in URL_KEYS}
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    for key in URL_KEYS:
        os.environ.pop(key, None)

    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from google.adk.agents import Agent
        from google.adk.tools.agent_tool import AgentTool
        from agents.creative_director.agent import (
            check_specialist_response,
            guard_quality_gate,
            start_campaign,
        )

        scenario_results = []
        final_states = []
        for case in cases:
            ctx = SimpleNamespace(state={})
            initialized = start_campaign(case["name"], ctx)
            if initialized.get("status") != "success":
                raise AssertionError(
                    f"Could not initialize offline fixture {case['name']!r}: "
                    f"{initialized!r}"
                )

            step_results = []
            guard_blocked = []
            callback_errors = []
            admitted_after_callback_error = []
            saw_callback_error = False

            for index, step in enumerate(case["steps"]):
                tool = AgentTool(agent=Agent(name=step["agent"]))
                args = {"request": step.get("request", f"offline step {index}")}
                guard_result = guard_quality_gate(tool, args, ctx)
                observation = {
                    "agent": step["agent"],
                    "guard_status": (
                        guard_result.get("status")
                        if isinstance(guard_result, dict) else "allowed"
                    ),
                    "admitted_by_guard": guard_result is None,
                    "callback_response_status": None,
                    "callback_error": None,
                }

                if guard_result is not None:
                    guard_blocked.append(step["agent"])
                else:
                    if saw_callback_error:
                        admitted_after_callback_error.append(step["agent"])
                    callback_response = check_specialist_response(
                        tool, args, ctx, step["response"]
                    )
                    if isinstance(callback_response, dict):
                        observation["callback_response_status"] = (
                            callback_response.get("status")
                        )
                        observation["callback_error"] = (
                            callback_response.get("error_message")
                        )
                        if callback_response.get("status") == "error":
                            callback_errors.append(step["agent"])
                            saw_callback_error = True
                    step_results.append(observation)
                    continue

                step_results.append(observation)

            expected = case["expected"]
            state = ctx.state
            downstream_after_error = expected["admitted_after_callback_error"]
            checks = {
                "quality_gate_approved": (
                    state.get("quality_gate_approved")
                    is expected["quality_gate_approved"]
                ),
                "quality_gate_rounds": (
                    state.get("quality_gate_rounds")
                    == expected["quality_gate_rounds"]
                ),
                "guard_blocked_agents": (
                    guard_blocked
                    == [
                        *expected["guard_blocked_agents"],
                        *downstream_after_error,
                    ]
                ),
                "callback_error_agents": (
                    callback_errors == expected["callback_error_agents"]
                ),
                "admitted_after_callback_error": (
                    admitted_after_callback_error == []
                ),
            }
            scenario_results.append({
                "scenario": case["name"],
                "passed": all(checks.values()),
                "checks": checks,
                "callback_observations": step_results,
                "simulated_workflow": {
                    "planned_agents": [step["agent"] for step in case["steps"]],
                    "guard_blocked_agents": guard_blocked,
                    "callback_error_agents": callback_errors,
                    "admitted_after_callback_error": (
                        admitted_after_callback_error
                    ),
                    "note": (
                        "Fixture-planned calls only; no remote specialist ran. "
                        "Dependent calls after callback errors must be blocked."
                    ),
                },
            })
            final_states.append(state)

        return {
            "scope": (
                "Offline callback characterization plus fixture-planned "
                "workflow sequences; no remote specialist calls."
            ),
            **summarize(final_states),
            "scenarios": scenario_results,
        }
    finally:
        if previous_dotenv_disabled is None:
            os.environ.pop("PYTHON_DOTENV_DISABLED", None)
        else:
            os.environ["PYTHON_DOTENV_DISABLED"] = previous_dotenv_disabled
        for key, value in previous_urls.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--states",
        type=Path,
        help="JSON array of locally exported Creative Director state objects",
    )
    args = parser.parse_args()
    if args.states:
        report = {
            "scope": "Supplied exported states; metrics depend on available fields.",
            **summarize(json.loads(args.states.read_text(encoding="utf-8"))),
        }
        exit_code = 0
    else:
        cases = json.loads(
            Path(__file__).with_name("cases.json").read_text(encoding="utf-8")
        )
        report = run_fixtures(cases)
        exit_code = 0 if all(item["passed"] for item in report["scenarios"]) else 1
    print(json.dumps(report, indent=2))
    raise SystemExit(exit_code)
