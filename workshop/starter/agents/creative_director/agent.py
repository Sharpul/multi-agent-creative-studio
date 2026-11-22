import logging
import os
import json

from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import RemoteA2aAgent
from google.adk.plugins.logging_plugin import LoggingPlugin
from google.adk.tools import FunctionTool
from google.adk.tools.agent_tool import AgentTool
from google.adk.apps import App
from google.adk.apps.app import EventsCompactionConfig
from google.adk.apps.llm_event_summarizer import LlmEventSummarizer
from google.adk.models import Gemini
from agents.creative_director.reliability import ReliableRemoteAgent
from dotenv import load_dotenv
load_dotenv()
try:
    from .retry import RETRY_CONFIG
    from .display_image_tool import display_image
    from .get_image_links_tool import get_image_links
except ImportError:
    from retry import RETRY_CONFIG
    from display_image_tool import display_image
    from get_image_links_tool import get_image_links

try:
    from .prompt import SYSTEM_INSTRUCTION_TEMPLATE
except ImportError:
    from prompt import SYSTEM_INSTRUCTION_TEMPLATE  # direct execution fallback

logger = logging.getLogger("ai_creative_studio.creative_director")
logger.setLevel(logging.INFO)

import re

MAX_CRITIC_ROUNDS = 3

GATE_APPROVED = "quality_gate_approved"
GATE_ROUNDS = "quality_gate_rounds"
GATE_EXHAUSTED = "quality_gate_exhausted"
SPECIALIST_FAILURE = "specialist_failure"


def guard_quality_gate(tool, args, tool_context):
    """Enforce Critic review limits and PM approval requirements."""

    state = tool_context.state
    rounds = state.get(GATE_ROUNDS, 0)
    approved = state.get(GATE_APPROVED, False)
    failure = state.get(SPECIALIST_FAILURE)

    if failure and tool.name in {
        "brand_strategist",
        "copywriter",
        "designer",
        "critic",
        "project_manager",
    }:
        return {
            "status": "blocked",
            "reason": (
                f"Specialist {failure['agent']} failed. "
                "Do not proceed to dependent specialists."
            ),
            "error_message": failure["error_message"],
        }

    # A complete campaign must be initialized first.
    # Standalone research and content requests remain available.
    if tool.name in {"critic", "project_manager"}:
        if not state.get("active_campaign"):
            return {
                "status": "blocked",
                "reason": (
                    "No active campaign. Call start_campaign "
                    "before campaign review or project creation."
                ),
            }

    # Block further campaign work after 3 rejected Critic reviews.
    if (
        state.get("active_campaign")
        and rounds >= MAX_CRITIC_ROUNDS
        and not approved
        and tool.name in {
            "copywriter",
            "designer",
            "critic",
            "project_manager",
        }
    ):
        return {
            "status": "blocked",
            "reason": "Campaign review limit exhausted.",
            "critic_rounds": rounds,
            "max_rounds": MAX_CRITIC_ROUNDS,
        }

    if tool.name == "critic":
        if rounds >= MAX_CRITIC_ROUNDS:
            return {
                "status": "blocked",
                "reason": "Maximum Critic review rounds reached.",
                "critic_rounds": rounds,
                "max_rounds": MAX_CRITIC_ROUNDS,
            }

    if tool.name == "project_manager":
        if not approved:
            return {
                "status": "blocked",
                "reason": "Critic approval required before Project Manager.",
                "critic_rounds": rounds,
                "max_rounds": MAX_CRITIC_ROUNDS,
            }

    # Block duplicate completed operations.
    if state.get("active_campaign"):
        completed = state.get("completed_requests", {})

        if tool.name == "designer":
            previous_request = completed.get("designer")

            if (
                previous_request is not None
                and previous_request == args.get("request")
            ):
                return {
                    "status": "blocked",
                    "reason": "Designer request already completed.",
                }

        if tool.name == "project_manager":
            if "project_manager" in completed:
                return {
                    "status": "blocked",
                    "reason": "Project Manager already completed for this campaign.",
                }

    # Prevent overlapping Critic reviews and creative changes.
    if state.get("active_campaign"):
        if state.get("critic_in_progress"):
            if tool.name in {"critic", "copywriter", "designer"}:
                return {
                    "status": "blocked",
                    "reason": "Critic review already in progress.",
                }

        if tool.name == "critic":
            state["critic_in_progress"] = True

    return None

def parse_critic_approval(response_text):
    """Approve only a complete, internally consistent Critic verdict."""

    if not isinstance(response_text, str):
        return False

    section_headers = list(re.finditer(
        r"^\s*\*\*([A-Z ]+):\*\*\s*$",
        response_text,
        re.IGNORECASE | re.MULTILINE,
    ))
    required_sections = {
        "POSTS REVIEW",
        "VISUALS REVIEW",
        "OVERALL ASSESSMENT",
    }
    sections = {}

    for index, header in enumerate(section_headers):
        name = header.group(1).upper()
        if name not in required_sections:
            continue
        if name in sections:
            return False
        end = (
            section_headers[index + 1].start()
            if index + 1 < len(section_headers)
            else len(response_text)
        )
        sections[name] = response_text[header.end():end]

    if set(sections) != required_sections:
        return False

    def extract_field(section, field):
        matches = re.findall(
            rf"^\s*-\s*{re.escape(field)}\b(.*)$",
            section,
            re.IGNORECASE | re.MULTILINE,
        )
        if len(matches) != 1:
            return None
        value = re.fullmatch(r"\s*:\s*([A-Z_]+)\s*", matches[0], re.IGNORECASE)
        return value.group(1).upper() if value else None

    post_status = extract_field(sections["POSTS REVIEW"], "Status")
    visual_status = extract_field(sections["VISUALS REVIEW"], "Status")
    overall_approved = extract_field(
        sections["OVERALL ASSESSMENT"], "All Approved"
    )

    return (
        post_status == "APPROVED"
        and visual_status == "APPROVED"
        and overall_approved == "YES"
    )

def record_critic_verdict(tool, tool_context, tool_response):
    """Track Critic verdict and enforce the review limit."""

    if tool.name != "critic":
        return None

    state = tool_context.state

    # The Critic has finished its review.
    state["critic_in_progress"] = False

    rounds = state.get(GATE_ROUNDS, 0) + 1

    state[GATE_ROUNDS] = rounds

    if isinstance(tool_response, dict):
        response_text = str(tool_response.get("result", ""))
    else:
        response_text = str(tool_response)

    approved = (
        parse_critic_approval(response_text)
        and rounds <= MAX_CRITIC_ROUNDS
    )

    state[GATE_APPROVED] = approved
    state[GATE_EXHAUSTED] = (
        rounds >= MAX_CRITIC_ROUNDS and not approved
    )

    if not approved and rounds >= MAX_CRITIC_ROUNDS:
        return {
            "status": "rejected",
            "critic_rounds": rounds,
            "max_rounds": MAX_CRITIC_ROUNDS,
            "instruction": (
                "Maximum Critic review rounds reached. "
                "Stop revisions and do not call Project Manager."
            ),
        }

    return None

def check_specialist_response(tool, args, tool_context, tool_response):
    """Detect errors returned by remote A2A specialists."""

    if not isinstance(tool, AgentTool):
        return None

    if tool_context.state.get(SPECIALIST_FAILURE):
        return None

    if (
        isinstance(tool_response, dict)
        and isinstance(tool_response.get("status"), str)
        and tool_response["status"].lower() == "blocked"
    ):
        return None

    # Decode JSON-formatted responses so structured errors are detected.
    if isinstance(tool_response, str) and tool_response.strip():
        try:
            decoded = json.loads(tool_response)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(decoded, dict) and (
                decoded.get("error") or decoded.get("error_message")
            ):
                tool_response = decoded

    # Reject malformed responses and explicit specialist failures.
    error_message = None

    if isinstance(tool_response, str) and tool_response.strip().upper().startswith("ERROR:"):
        error_message = tool_response.strip()

    elif not isinstance(tool_response, (str, dict)):
        error_message = "Remote specialist returned an unsupported response type"

    elif isinstance(tool_response, dict):
        status = tool_response.get("status")

        if not tool_response:
            error_message = "Remote specialist returned an empty response"
            if tool.name == "critic":
                tool_context.state["critic_in_progress"] = False

        elif "status" in tool_response and not isinstance(status, str):
            error_message = "Remote specialist returned an invalid status"

        elif isinstance(status, str) and status.lower() in {
            "error", "failed", "failure"
        }:
            error_message = str(
                tool_response.get("error_message")
                or tool_response.get("error")
                or tool_response.get("message")
                or "Remote specialist reported failure"
            )

        elif tool_response.get("success") is False:
            error_message = str(
                tool_response.get("error_message")
                or tool_response.get("error")
                or tool_response.get("message")
                or "Remote specialist reported failure"
            )

        elif "result" in tool_response and (
            tool_response["result"] is None
            or tool_response["result"] == []
        ):
            error_message = "Remote specialist returned an invalid result"

    if error_message:
        if tool.name == "critic":
            tool_context.state["critic_in_progress"] = False

        tool_context.state[SPECIALIST_FAILURE] = {
            "agent": tool.name,
            "error_message": error_message,
        }

        logger.error(
            "Remote specialist %s returned %s",
            tool.name,
            error_message,
        )

        return {
            "status": "error",
            "agent": tool.name,
            "error_message": error_message,
            "instruction": (
                "Do not proceed to dependent agents. "
                "Report the failure to the user."
            ),
        }

    # NEW: Check A2A errors first, including empty responses
    if isinstance(tool_response, str):
        if not tool_response.strip():
            error_message = "Remote specialist returned an empty response"

            if tool.name == "critic":
                tool_context.state["critic_in_progress"] = False

            tool_context.state[SPECIALIST_FAILURE] = {
                "agent": tool.name,
                "error_message": error_message,
            }
            logger.error(
                "Remote specialist %s returned an empty response",
                tool.name,
            )
            return {
                "status": "error",
                "agent": tool.name,
                "error_message": error_message,
                "instruction": (
                    "Do not proceed to dependent agents. "
                    "Report the failure to the user."
                ),
            }

    elif isinstance(tool_response, dict):
        error = tool_response.get("error_message") or tool_response.get("error")

        if error:
            if tool.name == "critic":
                tool_context.state["critic_in_progress"] = False

            logger.error(
                "Remote specialist %s failed: %s",
                tool.name,
                error,
            )
            error_message = str(error)
            tool_context.state[SPECIALIST_FAILURE] = {
                "agent": tool.name,
                "error_message": error_message,
            }
            return {
                "status": "error",
                "agent": tool.name,
                "error_message": error_message,
                "instruction": (
                    "The specialist failed. Do not treat this as success. "
                    "Do not proceed to dependent agents. "
                    "Report the actual error to the user."
                ),
            }

    else:
        return None

    # NEW: Record Critic verdict only after error checks
    if tool.name == "critic":
        return record_critic_verdict(
            tool,
            tool_context,
            tool_response,
        )

    if tool.name in {
        "brand_strategist",
        "copywriter",
        "designer",
        "project_manager",
    }:
        output = (
            tool_response.get("result")
            if isinstance(tool_response, dict)
            else tool_response
        )

        if isinstance(output, str) and output.strip():
            # Preserve the successful result in campaign state.
            # Save outputs only when a campaign has initialized storage.
            if "completed_outputs" in tool_context.state:
                tool_context.state["completed_outputs"][tool.name] = output

                # Remember which request completed successfully.
                if "completed_requests" in tool_context.state:
                    tool_context.state["completed_requests"][tool.name] = args.get("request")

            # Updated creative work requires fresh Critic approval.
            if tool.name in {"copywriter", "designer"}:
                tool_context.state[GATE_APPROVED] = False

    return None


def start_campaign(campaign_name: str, tool_context):
    """Initialize quality-gate state for a new campaign."""

    if not campaign_name.strip():
        return {
            "status": "error",
            "message": "Campaign name is required.",
        }

    state = tool_context.state

    existing_campaign = state.get("active_campaign")

    if existing_campaign:
        return {
            "status": "blocked",
            "message": (
                "An active campaign already exists in this session. "
                "Start a new ADK session for another campaign."
            ),
        }

    state[SPECIALIST_FAILURE] = None
    state[GATE_ROUNDS] = 0
    state[GATE_APPROVED] = False
    state[GATE_EXHAUSTED] = False
    state["completed_requests"] = {}
    state["critic_in_progress"] = False
    state["completed_outputs"] = {}
    state["active_campaign"] = campaign_name.strip()

    logger.info(
        "Started campaign: %s",
        campaign_name,
    )

    return {
        "status": "success",
        "campaign": campaign_name,
        "message": "Campaign initialized. Critic review counter reset.",
    }

def create_creative_director():
    """
    Create the Creative Director orchestrator.
    Reads specialist URLs from environment variables at runtime.
    """
    # Read specialist URLs from environment
    copywriter_url = os.getenv("COPYWRITER_AGENT_URL")
    designer_url = os.getenv("DESIGNER_AGENT_URL")
    strategist_url = os.getenv("STRATEGIST_AGENT_URL")
    critic_url = os.getenv("CRITIC_AGENT_URL")
    pm_url = os.getenv("PM_AGENT_URL")

    available_agents_list = []
    agent_tools = [
        FunctionTool(func=start_campaign),
        FunctionTool(func=display_image),
        FunctionTool(func=get_image_links),
    ]

    specialists = [
        (
            "brand_strategist",
            strategist_url,
            "Researches market trends, competitors, and audience insights",
        ),
        (
            "copywriter",
            copywriter_url,
            "Creates three Instagram captions using brand research",
        ),
        (
            "designer",
            designer_url,
            "Generates campaign images and uploads them to GCS",
        ),
        (
            "critic",
            critic_url,
            "Reviews captions and images and returns quality verdicts",
        ),
        (
            "project_manager",
            pm_url,
            "Creates campaign timelines, tasks, budgets, and milestones",
        ),
    ]

    for name, url, description in specialists:
        if not url:
            logger.warning("%s URL is not configured", name)
            continue

        url = url.rstrip("/")

        available_agents_list.append(
            f"- **{name}**: {description}"
        )

        remote_agent = ReliableRemoteAgent(
            name=name,
            description=description,
            agent_card=f"{url}/.well-known/agent.json",
            timeout=180.0,
        )

        agent_tools.append(
            AgentTool(agent=remote_agent)
        )

        logger.info("Registered remote agent %s at %s", name, url)


    available_agents_text = (
        "\n".join(available_agents_list)
        if available_agents_list
        else "No specialist agents configured. Set agent URLs in environment variables."
    )

    system_instruction = SYSTEM_INSTRUCTION_TEMPLATE.format(
        available_agents=available_agents_text
    )

    from google.genai import types
    generation_config = types.GenerateContentConfig(
        max_output_tokens=20000,
        temperature=0.2,
        http_options=types.HttpOptions(
            retry_options=RETRY_CONFIG,
            timeout=120_000,  # 120 second timeout for model calls
        ),
    )

    agent = Agent(
        name="creative_director",
        model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        description="Creative Director orchestrator that coordinates specialist agents",
        instruction=system_instruction,
        tools=agent_tools,
        generate_content_config=generation_config,
        before_tool_callback=guard_quality_gate,
        after_tool_callback=check_specialist_response,
    )

    compaction_config = EventsCompactionConfig(
        summarizer=LlmEventSummarizer(
            llm=Gemini(
                model_id=os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
            )
        ),
        compaction_interval=3,
        overlap_size=1,
    )

    app = App(
        name="creative_director",
        root_agent=agent,
        events_compaction_config=compaction_config,
        plugins=[LoggingPlugin()],
    )

    return agent, app

root_agent, root_app = create_creative_director()
