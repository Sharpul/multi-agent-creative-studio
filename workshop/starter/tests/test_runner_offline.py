"""Real ADK Runner/tool dispatch with scripted model and local fake specialists.
These are orchestration integration tests, not distributed cloud integration tests.
"""
import asyncio
import pytest
from google.adk.agents import Agent, BaseAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.events import Event
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.genai import types
from agents.creative_director.agent import start_campaign, guard_quality_gate, check_specialist_response
from test_quality_gate import verdict


class ScriptedModel(BaseLlm):
    script: list
    index: int = 0

    async def generate_content_async(self, llm_request, stream=False):
        if self.index < len(self.script):
            name, args = self.script[self.index]
            self.index += 1
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        else:
            part = types.Part.from_text(text="Offline dispatch complete")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class Specialist(BaseAgent):
    responses: list[str]
    calls: int = 0

    async def _run_async_impl(self, ctx):
        text = self.responses[min(self.calls, len(self.responses)-1)]
        self.calls += 1
        yield Event(author=self.name, content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))


@pytest.mark.parametrize("mode", ["approved", "revision", "exhausted", "failure", "pm_failure"])
def test_adk_dispatch(mode):
    async def run():
        reviews = [verdict()]
        if mode == "revision":
            reviews = [verdict(overall="NO"), verdict()]
        elif mode == "exhausted":
            reviews = [verdict(overall="NO")]*3
        critic = Specialist(name="critic", responses=reviews)
        copy = Specialist(name="copywriter", responses=["" if mode == "failure" else "captions"])
        pm = Specialist(name="project_manager", responses=['{"error":"PM unavailable"}' if mode == "pm_failure" else "timeline"])
        script = [("start_campaign", {"campaign_name": "Offline"}),
                  ("project_manager", {"request": "try before approval"}),
                  ("copywriter", {"request": "draft"})]
        for index, _ in enumerate(reviews):
            script.append(("critic", {"request": "review"}))
            if mode == "revision" and index == 0:
                script.append(("copywriter", {"request": "revise"}))
        if mode == "exhausted":
            script.append(("critic", {"request": "fourth"}))
        script.append(("project_manager", {"request": "plan"}))
        agent = Agent(name="offline_director", model=ScriptedModel(model="offline", script=script),
                      tools=[FunctionTool(start_campaign), AgentTool(agent=copy), AgentTool(agent=critic), AgentTool(agent=pm)],
                      before_tool_callback=guard_quality_gate, after_tool_callback=check_specialist_response)
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name="offline", user_id="user")
        runner = Runner(app_name="offline", agent=agent, session_service=sessions)
        try:
            events = [e async for e in runner.run_async(user_id="user", session_id=session.id,
                new_message=types.Content(role="user", parts=[types.Part.from_text(text="offline")]))]
            final = await sessions.get_session(app_name="offline", user_id="user", session_id=session.id)
        finally:
            await runner.close()
        return final.state, critic.calls, pm.calls, events
    state, reviews, pm_calls, events = asyncio.run(run())
    assert events
    assert pm_calls == (1 if mode in {"approved", "revision", "pm_failure"} else 0)
    assert reviews == {"approved": 1, "revision": 2, "exhausted": 3, "failure": 0, "pm_failure": 1}[mode]
    if mode == "failure":
        assert state["specialist_failure"]["agent"] == "copywriter"
    if mode == "pm_failure":
        assert state["quality_gate_approved"]
        assert state["completed_outputs"]["copywriter"] == "captions"
        assert state["specialist_failure"]["error_message"] == "PM unavailable"
