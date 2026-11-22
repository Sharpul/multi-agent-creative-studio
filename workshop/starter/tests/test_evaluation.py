import json
from pathlib import Path
from evaluation.offline import run_fixtures, summarize


def test_fixture_regressions():
    cases = json.loads((Path(__file__).parents[1]/"evaluation/cases.json").read_text())
    report = run_fixtures(cases)
    assert len(report["scenarios"]) == 5
    assert all(r["passed"] for r in report["scenarios"])
    assert report["critic_approval_rate"] == 0.6
    assert report["total_critic_reviews"] == 7
    assert report["average_critic_review_count"] == 1.4
    assert report["review_exhaustion_count"] == 1
    assert report["campaign_completion_success_rate"] is None
    assert report["specialist_failure_rate"] is None
    assert report["specialist_latency"] is None


def test_callback_error_blocks_downstream_specialist():
    cases = json.loads((Path(__file__).parents[1]/"evaluation/cases.json").read_text())
    report = run_fixtures(cases)
    failure = next(
        scenario for scenario in report["scenarios"]
        if scenario["scenario"] == "specialist_failure"
    )
    assert failure["simulated_workflow"]["callback_error_agents"] == ["copywriter"]
    assert failure["simulated_workflow"]["guard_blocked_agents"] == ["designer"]
    assert failure["simulated_workflow"]["admitted_after_callback_error"] == []


def test_empty_denominators():
    report = summarize([])
    assert report["campaign_completion_success_rate"] is None
    assert report["critic_approval_rate"] is None
    assert report["specialist_failure_rate"] is None
    assert report["specialist_latency"] is None
