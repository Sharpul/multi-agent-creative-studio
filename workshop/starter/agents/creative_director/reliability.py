"""Small session safeguards at the existing ADK/A2A boundary; no remote retries."""
import hashlib
import json
import re
import time

from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.events import Event
from google.genai import types

SPECIALISTS = {"brand_strategist", "copywriter", "designer", "critic", "project_manager"}
BLOCKED = "_studio_guard_blocked"


class ReliableRemoteAgent(RemoteA2aAgent):
    """Preserve error-only Events that AgentTool otherwise drops when merging text."""

    async def _run_async_impl(self, ctx):
        try:
            async for event in super()._run_async_impl(ctx):
                if event.error_message:
                    yield self._error_event(ctx, event.error_message)
                    return
                yield event
        except Exception as exc:
            yield self._error_event(ctx, str(exc) or type(exc).__name__)

    def _error_event(self, ctx, message):
        return Event(
            author=self.name,
            invocation_id=ctx.invocation_id,
            content=types.Content(role="model", parts=[types.Part.from_text(
                text=json.dumps({"status": "error", "error_message": message})
            )]),
        )


def guard_specialist(name, state, args):
    if name not in SPECIALISTS:
        return None
    reason = None
    if state.get("specialist_failure"):
        reason = "A specialist failed. Preserve outputs and reconcile side effects before recovery."
    elif state.get("specialist_inflight"):
        reason = "A specialist operation is already in progress; wait for its result."
    elif state.get("quality_gate_exhausted"):
        reason = "Three Critic reviews exhausted. Preserve unapproved drafts."
    elif name == "designer" and request_key(args) in state.get("designer_attempts", []):
        reason = "Identical Designer request already attempted. Preserve its outputs; reconcile before replay."
    elif name == "project_manager" and state.get("pm_attempted"):
        reason = "Project Manager already attempted. Reconcile existing Notion records before replay."
    if reason:
        return {BLOCKED: True, "status": "blocked", "reason": reason}
    return None


def request_key(args):
    return hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()


def begin_specialist(name, state, args):
    if name not in SPECIALISTS:
        return
    if name == "designer":
        state["designer_attempts"] = [*state.get("designer_attempts", []), request_key(args)]
    state["specialist_inflight"] = name
    state["specialist_started_at"] = time.monotonic()
    if name in {"brand_strategist", "copywriter", "designer", "critic"}:
        state["quality_gate_approved"] = False
    if name == "project_manager":
        state["pm_attempted"] = True


def specialist_result(response):
    """Accept schema-less ADK text and the existing legacy {result: text} envelope."""
    if isinstance(response, str) and response.lstrip().startswith("{"):
        try:
            decoded = json.loads(response)
        except ValueError:
            pass  # ADK text need not be JSON; do not parse arbitrary prose.
        else:
            if isinstance(decoded, dict):
                status = decoded.get("status")
                failed = isinstance(status, str) and status.lower() in {"error", "failed", "failure", "blocked"}
                if (decoded.get("error") or decoded.get("error_message") or failed
                        or decoded.get("success") is False or "result" in decoded
                        or not set(decoded).difference({"status", "success"})):
                    response = decoded
    if isinstance(response, dict):
        error = response.get("error_message") or response.get("error")
        status = response.get("status")
        failed = isinstance(status, str) and status.lower() in {"error", "failed", "failure", "blocked"}
        if error or failed or response.get("success") is False:
            return None, str(error or response.get("message") or "Specialist explicitly reported failure")
        response = response.get("result")
    if not isinstance(response, str):
        return None, "Remote specialist returned a missing result or unsupported response format"
    if not response.strip():
        return None, "Remote specialist returned an empty response"
    if re.match(r"^\s*(?:ERROR|FAILED):", response, re.I):
        return None, response
    return response, None


def finish_specialist(name, state, text, error):
    started = state.get("specialist_started_at")
    elapsed = max(0.0, time.monotonic() - started) if isinstance(started, (int, float)) else None
    state["specialist_inflight"] = None
    metrics = list(state.get("specialist_metrics", []))
    metrics.append({"agent": name, "failed": bool(error), "latency_seconds": elapsed})
    state["specialist_metrics"] = metrics
    if error:
        failure = {"agent": name, "error_message": error}
        state["specialist_failure"] = failure
        return {"status": "error", **failure, "instruction": (
            "Do not proceed to dependent agents. Preserve completed outputs. "
            "Reconcile images and Notion records before recovery in a new session."
        )}
    outputs = dict(state.get("completed_outputs", {}))
    outputs[name] = text
    state["completed_outputs"] = outputs
    return None
