import asyncio
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import pytest
from google.adk.events import Event
from agents.creative_director import agent as director
from agents.creative_director import reliability
from agents.designer import image_gen_tool as images
from agents.project_manager.agent import guard_notion_write, handle_notion_error
from test_quality_gate import verdict


def context():
    ctx = NS(state={})
    director.start_campaign("Offline campaign", ctx)
    return ctx


def call(ctx, name, response, request="offline"):
    tool = NS(name=name)
    with patch.object(director, "AgentTool", NS):
        blocked = director.guard_quality_gate(tool, {"request": request}, ctx)
        if blocked:
            # Real ADK invokes the after callback even when the guard blocks.
            assert director.check_specialist_response(tool, {}, ctx, blocked) is None
            return blocked
        return director.check_specialist_response(
            tool, {"request": request}, ctx, response
        )


@pytest.mark.parametrize("response", [None, [], 12, {}, {"result": None}, {"result": []}, {"status": "failed", "message": "upstream failed"}, {"success": False}, '{"status":"error","error":"HTTP 503"}', {"status": ["unsupported"]}])
def test_invalid_response_blocks_dependencies(response):
    ctx = context()
    assert call(ctx, "copywriter", response)["status"] == "error"
    assert call(ctx, "designer", "never executed")["status"] == "blocked"
    assert "designer" not in ctx.state.get("completed_outputs", {})
    assert ctx.state["specialist_failure"]["agent"] == "copywriter"


@pytest.mark.parametrize("message", ["Request timed out", "Connection refused", "HTTP 429", "HTTP 500", "HTTP 503"])
def test_actual_adk_error_event_message_preserved(message):
    async def fake(self, ctx):
        yield Event(author=self.name, error_message=message)
    async def run():
        agent = reliability.ReliableRemoteAgent(name="copywriter", agent_card="https://offline.invalid/card")
        with patch.object(reliability.RemoteA2aAgent, "_run_async_impl", fake):
            return [e async for e in agent._run_async_impl(NS(invocation_id="offline"))]
    events = asyncio.run(run())
    result = call(context(), "copywriter", events[0].content.parts[0].text)
    assert result["error_message"] == message


def test_raised_transport_exception_preserved():
    async def broken(self, ctx):
        raise TimeoutError("original transport timeout")
        yield  # async generator contract
    async def run():
        agent = reliability.ReliableRemoteAgent(name="designer", agent_card="https://offline.invalid/card")
        with patch.object(reliability.RemoteA2aAgent, "_run_async_impl", broken):
            return [e async for e in agent._run_async_impl(NS(invocation_id="offline"))]
    text = asyncio.run(run())[0].content.parts[0].text
    assert reliability.specialist_result(text)[1] == "original transport timeout"


@pytest.mark.parametrize("response", [
    verdict()+verdict(posts="NEEDS_REVISION"),
    verdict().replace("- Status: APPROVED", "- Status: APPROVED\n- Status: NEEDS_REVISION", 1),
    verdict().replace("- All Approved: YES", ""),
    verdict()+"\n- All Approved: YES but maybe NO\n",
    verdict().replace("- Status: APPROVED", "- Status APPROVED", 1),
    None,
    42,
    [],
    {},
])
def test_ambiguous_verdict_rejected(response):
    assert director.parse_critic_approval(response) is False


def test_revision_then_pm_failure_retains_assets():
    ctx = context()
    for name in ("brand_strategist", "copywriter", "designer"):
        assert call(ctx, name, name+" artifact") is None
    call(ctx, "critic", verdict(posts="NEEDS_REVISION", overall="NO"))
    call(ctx, "copywriter", "revised captions")
    call(ctx, "critic", verdict())
    assert ctx.state[director.GATE_ROUNDS] == 2
    assert call(ctx, "project_manager", {"error": "PM unavailable"})["status"] == "error"
    assert ctx.state["completed_outputs"]["designer"] == "designer artifact"
    assert ctx.state[director.GATE_APPROVED]
    assert call(ctx, "project_manager", "duplicate")["status"] == "blocked"


@pytest.mark.parametrize("name", ["copywriter", "designer"])
def test_creative_output_changes_revoke_approval(name):
    ctx = context()
    call(ctx, "critic", verdict())
    call(ctx, name, "changed creative context")
    assert not ctx.state[director.GATE_APPROVED]
    assert call(ctx, "project_manager", "no")["status"] == "blocked"


def test_failed_creative_call_does_not_invalidate_approval():
    ctx = context()
    call(ctx, "critic", verdict())
    assert ctx.state[director.GATE_APPROVED]

    failed = call(ctx, "copywriter", {"error": "service unavailable"})

    assert failed["status"] == "error"
    assert ctx.state[director.GATE_APPROVED]
    assert call(ctx, "project_manager", "no")["status"] == "blocked"


def test_exhaustion_blocks_fourth_review_and_revisions():
    ctx = context()
    for _ in range(3):
        call(ctx, "critic", verdict(overall="NO"))
    for name in ("critic", "designer", "copywriter", "project_manager"):
        assert call(ctx, name, "no")["status"] == "blocked"
    assert ctx.state[director.GATE_ROUNDS] == 3


def test_third_review_can_approve():
    ctx = context()
    call(ctx, "critic", verdict(overall="NO"))
    call(ctx, "critic", verdict(overall="NO"))
    call(ctx, "critic", verdict())
    assert ctx.state[director.GATE_ROUNDS] == 3
    assert call(ctx, "project_manager", "timeline") is None


def test_state_isolation():
    first, second = context(), context()
    call(first, "critic", verdict())
    assert not second.state[director.GATE_APPROVED]
    assert second.state[director.GATE_ROUNDS] == 0


def test_pm_and_designer_replay_blocked():
    ctx = context()
    assert call(ctx, "designer", "image") is None
    assert call(ctx, "designer", "duplicate")["status"] == "blocked"
    assert call(ctx, "designer", "revised image", request="revision 1") is None
    call(ctx, "critic", verdict())
    assert call(ctx, "project_manager", "timeline") is None
    assert call(ctx, "project_manager", "duplicate")["status"] == "blocked"


def test_parallel_specialist_blocked():
    ctx = context()
    assert director.guard_quality_gate(NS(name="critic"), {}, ctx) is None
    assert director.guard_quality_gate(NS(name="critic"), {}, ctx)["status"] == "blocked"
    assert director.guard_quality_gate(NS(name="designer"), {}, ctx)["status"] == "blocked"
    director.record_critic_verdict(NS(name="critic"), ctx, verdict())
    assert ctx.state[director.GATE_ROUNDS] == 1


def test_failed_critic_transport_does_not_count_as_review():
    ctx = context()
    call(ctx, "critic", {"error": "timeout"})
    assert ctx.state[director.GATE_ROUNDS] == 0
    call(ctx, "critic", "blocked")
    assert ctx.state[director.GATE_ROUNDS] == 0


def test_notion_write_guard_allows_reads_and_distinct_writes():
    ctx = NS(state={})
    args = {"parent": {"database_id": "offline"}, "properties": {"Name": "campaign"}}
    assert guard_notion_write(NS(name="API-post-page"), args, ctx) is None
    assert guard_notion_write(NS(name="API-post-page"), args, ctx)["isError"]
    assert guard_notion_write(NS(name="API-post-database-query"), args, ctx) is None
    assert guard_notion_write(NS(name="API-post-page"), {"different": "task"}, ctx) is None


@pytest.mark.parametrize("status", [400, 404, 429, 500, 503])
def test_notion_errors_not_success(status):
    result = handle_notion_error(NS(name="API-post-page"), {}, NS(state={}), {"structuredContent": {"status": status, "message": "actual error"}})
    assert result["error"] == "actual error"
    assert "complete text timeline" in result["instruction"]


@pytest.mark.parametrize("failure", [False, True])
def test_image_generation_not_repeated(monkeypatch, failure):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "offline")
    monkeypatch.setenv("GCS_IMAGES_BUCKET", "offline")
    generated = NS(candidates=[NS(content=NS(parts=[NS(inline_data=NS(data=b"fake", mime_type="image/png"))]))])
    client = Mock()
    client.models.generate_content.return_value = generated
    if failure:
        client.models.generate_content.side_effect = TimeoutError("unknown generation outcome")
    class Context:
        def __init__(self): self.state = {}
        async def save_artifact(self, *args): raise ValueError("No artifact service")
    ctx = Context()
    async def run():
        with patch.object(images.genai, "Client", return_value=client), patch.object(images.storage, "Client") as storage:
            one = await images.generate_image("post1", "offline prompt", "1:1", ctx)
            two = await images.generate_image("post1", "offline prompt", "1:1", ctx)
            assert storage.return_value.bucket.return_value.blob.return_value.upload_from_file.call_count == (0 if failure else 1)
        return one, two
    one, two = asyncio.run(run())
    assert client.models.generate_content.call_count == 1
    assert client.models.generate_content.call_args.kwargs["config"].http_options.retry_options.attempts == 1
    assert one == two
    assert one["status"] == ("error" if failure else "success")
    if failure: assert one["error"] == "unknown generation outcome"


def test_successful_upload_retained_after_artifact_failure(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "offline")
    monkeypatch.setenv("GCS_IMAGES_BUCKET", "offline")
    client = Mock()
    client.models.generate_content.return_value = NS(candidates=[NS(content=NS(parts=[NS(inline_data=NS(data=b"image", mime_type="image/png"))]))])
    class Context:
        state = {}
        async def save_artifact(self, *args): raise RuntimeError("artifact unavailable")
    async def run():
        with patch.object(images.genai, "Client", return_value=client), patch.object(images.storage, "Client"):
            return await images.generate_image("post1", "prompt", "1:1", Context())
    result = asyncio.run(run())
    assert result["status"] == "success"
    assert result["gcs_uri"].startswith("gs://offline/")
    assert result["artifact_warning"] == "artifact unavailable"


@pytest.mark.parametrize("uris", [["gs://foreign/private.png"], ["https://example.invalid/image"], ["gs://allowed/"], [], [None]])
def test_signing_rejects_invalid_bucket_input(monkeypatch, uris):
    from agents.creative_director.get_image_links_tool import get_image_links
    monkeypatch.setenv("GCS_IMAGES_BUCKET", "allowed")
    assert get_image_links(uris)["status"] == "error"


def test_explicit_text_error():
    assert call(context(), "designer", "ERROR: image failed")["error_message"] == "ERROR: image failed"


def test_legitimate_prose_not_misread_as_error():
    text = "Campaign copy: avoid the word ERROR: in your caption."
    assert reliability.specialist_result(text) == (text, None)


def test_review_and_display_reject_foreign_bucket(monkeypatch):
    from agents.critic.image_review_tool import review_image
    from agents.creative_director.display_image_tool import display_image
    monkeypatch.setenv("GCS_IMAGES_BUCKET", "allowed")
    assert review_image("gs://foreign/image.png", "post1", "brief").status == "error"
    assert asyncio.run(display_image("gs://foreign/image.png", "post1", NS(state={})))["status"] == "error"


def test_signing_without_identity_fails_closed(monkeypatch):
    import google.auth
    from google.cloud import storage
    from agents.creative_director.get_image_links_tool import get_image_links
    monkeypatch.setenv("GCS_IMAGES_BUCKET", "allowed")
    monkeypatch.delenv("SIGNING_SERVICE_ACCOUNT", raising=False)
    with patch.object(google.auth, "default", return_value=(NS(), None)), patch.object(storage, "Client"):
        result = get_image_links(["gs://allowed/image.png"])
    assert result["status"] == "error"
    assert "Signing identity unavailable" in result["error"]


def test_signed_url_has_one_hour_expiration(monkeypatch):
    from datetime import timedelta
    import google.auth
    from google.cloud import storage
    from google.auth import iam
    from google.oauth2 import service_account
    from agents.creative_director.get_image_links_tool import get_image_links
    monkeypatch.setenv("GCS_IMAGES_BUCKET", "allowed")
    monkeypatch.setenv("SIGNING_SERVICE_ACCOUNT", "offline@example.invalid")
    with patch.object(google.auth, "default", return_value=(Mock(), None)), patch.object(storage, "Client") as client, patch.object(iam, "Signer"), patch.object(service_account, "Credentials"):
        blob = client.return_value.bucket.return_value.blob.return_value
        blob.generate_signed_url.return_value = "https://offline.invalid/signed"
        result = get_image_links(["gs://allowed/image.png"])
    assert result["signed"] is True
    assert blob.generate_signed_url.call_args.kwargs["expiration"] == timedelta(hours=1)


def test_critic_prompt_matches_quality_gate():
    from agents.critic.agent import SYSTEM_INSTRUCTION
    assert "Treat NOT_REVIEWED as NOT approved" in SYSTEM_INSTRUCTION


def test_runtime_config_registers_remote_a2a_agents(monkeypatch):
    for key in ("COPYWRITER_AGENT_URL", "DESIGNER_AGENT_URL", "STRATEGIST_AGENT_URL", "CRITIC_AGENT_URL", "PM_AGENT_URL"):
        monkeypatch.setenv(key, "https://offline.invalid")
    agent, app = director.create_creative_director()
    remotes = [tool.agent for tool in agent.tools if isinstance(tool, director.AgentTool)]
    assert len(remotes) == 5
    assert all(isinstance(remote, director.RemoteA2aAgent) for remote in remotes)
    assert agent.before_tool_callback is director.guard_quality_gate
    assert agent.after_tool_callback is director.check_specialist_response
    assert len(app.plugins) == 1
    assert isinstance(app.plugins[0], director.LoggingPlugin)


def test_crlf_verdict_accepted():
    assert director.parse_critic_approval(verdict().replace("\n", "\r\n"))


def test_json_deliverable_is_legitimate_adk_text():
    text = '{"captions": ["First caption", "Second caption", "Third caption"]}'
    assert reliability.specialist_result(text) == (text, None)


def test_json_image_deliverable_is_legitimate_adk_text():
    text = '{"status":"success", "gcs_uri":"gs://offline/image.png"}'
    assert reliability.specialist_result(text) == (text, None)
    assert reliability.specialist_result('{"status":"success"}')[1]


def test_reasoning_retry_config_is_bounded_and_uses_sdk_jitter():
    from agents.creative_director.retry import RETRY_CONFIG
    from google.genai._api_client import retry_args
    config = retry_args(RETRY_CONFIG)
    assert RETRY_CONFIG.attempts == 5
    assert set(RETRY_CONFIG.http_status_codes) == {429, 500, 503, 504}
    assert config["wait"].__class__.__name__ == "wait_exponential_jitter"

def test_empty_critic_response_releases_in_progress_marker():
    ctx = context()

    # First Critic call begins.
    assert director.guard_quality_gate(
        NS(name="critic"), {}, ctx
    ) is None

    assert ctx.state["critic_in_progress"] is True

    # Critic returns an empty response.
    with patch.object(director, "AgentTool", NS):
        result = director.check_specialist_response(
            NS(name="critic"), {}, ctx, ""
        )

    # Failure is reported and execution marker is cleared.
    assert result["status"] == "error"
    assert ctx.state["critic_in_progress"] is False

    # The existing failure latch must remain active.
    assert ctx.state[director.SPECIALIST_FAILURE] is not None

def test_director_wires_reliable_remote_agent():
    import ast
    import inspect

    source = inspect.getsource(director)
    tree = ast.parse(source)

    # Confirm the orchestrator constructs the reliable wrapper.
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "ReliableRemoteAgent"
        for node in ast.walk(tree)
    )

    # Confirm both lifecycle callbacks are configured.
    assert any(
        isinstance(node, ast.keyword)
        and node.arg == "before_tool_callback"
        and isinstance(node.value, ast.Name)
        and node.value.id == "guard_quality_gate"
        for node in ast.walk(tree)
    )

    assert any(
        isinstance(node, ast.keyword)
        and node.arg == "after_tool_callback"
        and isinstance(node.value, ast.Name)
        and node.value.id == "check_specialist_response"
        for node in ast.walk(tree)
    )