import datetime
import json
import logging
import os
import urllib.error
import urllib.request

from google.adk.agents import Agent
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from dotenv import load_dotenv
try:
    from .retry import GENERATE_CONTENT_CONFIG
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG

from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from mcp import StdioServerParameters

load_dotenv()

logger = logging.getLogger("ai_creative_studio.project_manager")


def _notion_request(method: str, page_id: str, payload: dict | None = None) -> dict:
    """Use the official API to verify and repair MCP-created database rows."""
    token = os.environ["NOTION_TOKEN"]
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        f"https://api.notion.com/v1/pages/{page_id}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def _tool_data(response: dict) -> dict:
    """Read either the structured MCP result or its JSON text fallback."""
    structured = response.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    for item in response.get("content", []):
        if item.get("type") == "text":
            try:
                parsed = json.loads(item.get("text", ""))
                if isinstance(parsed, dict):
                    return parsed
            except (ValueError, TypeError):
                pass
    return {}


def _desired_properties(args: dict, actual: dict) -> dict:
    """Translate simple MCP arguments into typed Notion page properties."""
    result = {}
    for name, value in (args.get("properties") or {}).items():
        definition = actual.get(name)
        if not isinstance(definition, dict) or value is None:
            continue
        kind = definition.get("type")
        if kind == "title" and isinstance(value, str):
            result[name] = {"title": [{"text": {"content": value}}]}
        elif kind == "rich_text" and isinstance(value, str):
            result[name] = {"rich_text": [{"text": {"content": value}}]}
        elif kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            result[name] = {"number": value}
        elif kind == "date" and isinstance(value, str):
            result[name] = {"date": {"start": value}}
        elif kind == "status" and isinstance(value, str):
            result[name] = {"status": {"name": value}}
        elif kind == "select" and isinstance(value, str):
            result[name] = {"select": {"name": value}}
    return result


def _property_matches(actual: dict, desired: dict) -> bool:
    kind, expected = next(iter(desired.items()))
    observed = actual.get(kind)
    if kind in ("title", "rich_text"):
        text = "".join(x.get("plain_text", "") for x in (observed or []))
        return text == "".join(x["text"]["content"] for x in expected)
    if kind == "date":
        return bool(observed) and observed.get("start") == expected["start"]
    if kind in ("status", "select"):
        return bool(observed) and observed.get("name") == expected["name"]
    return observed == expected


def _required_fields_for_row(args: dict, actual: dict) -> list[str]:
    """Require complete rows for the two configured campaign databases."""
    database_id = str(args.get("database_id_or_url", "")).replace("-", "").lower()
    project_id = os.getenv("NOTION_PROJECT_DATABASE_ID", "").replace("-", "").lower()
    tasks_id = os.getenv("NOTION_TASKS_DATABASE_ID", "").replace("-", "").lower()
    if project_id and project_id in database_id:
        required = ["Name", "Budget", "Start Date", "End Date"]
    elif tasks_id and tasks_id in database_id:
        required = ["Name", "Owner", "Deadline", "Status"]
    else:
        return []
    return [field for field in required if field in actual]



def guard_notion_write(tool, args, tool_context):
    """Block identical non-idempotent write attempts, including unknown outcomes."""
    if tool.name not in {"API-post-page", "API-patch-block-children"}:
        return None
    import hashlib
    key = hashlib.sha256(json.dumps([tool.name, args], sort_keys=True).encode()).hexdigest()
    attempts = list(tool_context.state.get("notion_write_attempts", []))
    if key in attempts:
        return {"isError": True, "error": "Identical Notion write already attempted. Query existing records and reconcile; do not create a duplicate."}
    tool_context.state["notion_write_attempts"] = [*attempts, key]
    return None


def handle_notion_error(
    tool: BaseTool,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict,
) -> dict | None:
    """Convert Notion MCP errors into actionable recovery hints."""
    name = tool.name

    if not name.startswith("API-"):
        return None

    data = _tool_data(tool_response)

    # MCP may return an error in its structured or text response.
    status = data.get("status", data.get("status_code"))
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = None

    is_error = (
        tool_response.get("isError") is True
        or data.get("object") == "error"
        or data.get("isError") is True
        or (status is not None and status >= 400)
    )

    if not is_error:
        return None  # Preserve successful MCP responses.

    message = (data.get("message") or data.get("error")
               or tool_response.get("error") or "Notion request failed")

    if status == 400:
        hint = (
            "Check the database schema and property types. "
            "Use parent.database_id, not parent.page_id. "
            "Do not assign unsupported people properties."
        )
    elif status == 404:
        hint = (
            "Check the database or page ID and ensure the "
            "Notion integration has access to that database."
        )
    else:
        hint = (
            "Check the Notion MCP tool arguments, integration "
            "permissions, and server logs."
        )

    logger.warning("Notion MCP error: tool=%s status=%s", name, status)

    return {
        "success": False,
        "error": str(message),
        "recovery_hint": hint,
        "instruction": (
            "Continue producing the complete text timeline. "
            "Do not claim Notion persistence without verification."
        ),
    }



def get_system_instruction(project_database_id=None, tasks_database_id=None):
    # notion_section is empty when Notion is not configured, so the agent
    # receives no tool instructions for capabilities it doesn't have.
    notion_section = (
        f"""
Projects database ID: {project_database_id}
Tasks database ID: {tasks_database_id}

Also persist the project and tasks to these Notion databases.

IMPORTANT: This deployment uses the official Notion MCP server.

Available Notion tools include:
- API-retrieve-a-database: inspect database properties and their types.
- API-post-database-query: search existing database entries.
- API-post-page: create a new project or task page.
- API-retrieve-a-page: verify created pages.
- API-patch-page: update an existing page.
- API-patch-block-children: append content to a page.

NEVER call add_database_row. That tool is not available.

Before creating anything:
1. Retrieve both database schemas using API-retrieve-a-database.
2. Confirm the actual property names and types.
3. Query for an existing campaign with the same name to avoid duplicates.
4. Use the exact argument schema exposed by each MCP tool.

PROJECT CREATION:
Use API-post-page with the Projects database as parent.

Required project properties:
- Name: Notion title property
- Budget: Notion number property
- Start Date: Notion date property
- End Date: Notion date property

TASK CREATION:
Use API-post-page with the Tasks database as parent.

CRITICAL NOTION PARENT RULE:
When creating a project or task inside a database, the
API-post-page parent argument MUST use "database_id".

Correct:
{{"parent": {{"database_id": "<DATABASE_ID>"}}}}

Incorrect:
{{"parent": {{"page_id": "<DATABASE_ID>"}}}}

The Projects and Tasks IDs provided above are database IDs,
not page IDs. NEVER use page_id for either of them.
This rule applies to EVERY API-post-page call.

Required task properties:
- Name: Notion title property
- Owner: use its actual database property type
- Deadline: Notion date property
- Status: use an existing database status option

Use properly typed Notion API properties, not simple strings.

Example project properties:
{{
  "Name": {{"title": [{{"text": {{"content": "GreenBite Launch"}}}}]}},
  "Budget": {{"number": 5000}},
  "Start Date": {{"date": {{"start": "2026-11-12"}}}},
  "End Date": {{"date": {{"start": "2026-11-15"}}}}
}}

This is an example of the properties object, not the complete MCP
tool arguments. Follow the actual API-post-page tool schema.

Before creating a page, ensure all required properties are present.
If the database schema differs from these examples, use its actual types.

After creating each page:
1. Check whether the API-post-page response indicates success.
2. Capture the returned page ID.
3. Retrieve the page using API-retrieve-a-page.
4. Verify that all required properties were persisted.
5. If verification fails, report the incomplete page ID.
6. Never automatically create a duplicate page.
7. Treat timed-out writes as uncertain. Query existing pages/tasks before recovery.
   Identical write replays are blocked in the current session.

If Notion creation fails, still provide the complete text timeline.
Never claim that a Notion page was saved without confirmation.

If any Notion call fails, continue — the text timeline is always the primary deliverable.
Write your complete response AFTER all Notion operations are done (or have failed).

If image HTTPS links are provided in the input (under "Generated Images" from the Creative
Director), add them to the Notion project page body as a bulleted list under a
"Generated Images" heading after creating the project page.
"""
        if project_database_id
        else ""
    )

    return f"""
You are a Project Manager responsible for planning and coordinating
Instagram marketing campaigns.

Today's date: {datetime.date.today().strftime("%B %d, %Y")}

Your responsibilities:

1. Create a realistic campaign timeline starting from today's date.
   Never schedule tasks or milestones in the past.

2. Organize every campaign into four phases:
   - Strategy: audience research, positioning, campaign goals.
   - Creation: captions, images, creative assets.
   - Review: quality assurance, feedback, approvals.
   - Launch: scheduling, publishing, performance monitoring.

3. Create specific, actionable tasks.
   Every task must have:
   - Task name
   - Owner (role or team)
   - Deadline (specific date)
   - Status (Not Started, In Progress, or Completed)

4. Use the campaign brief to estimate a realistic schedule.
   Identify dependencies between tasks and avoid impossible deadlines.
   Do not claim tasks are completed unless the input confirms completion.

5. Provide a budget breakdown by category.
   Use the user's supplied budget if available.
   If no budget is supplied, label amounts as illustrative estimates,
   state the currency and assumptions, and avoid implying approval.

6. Identify important milestones and checkpoints.

7. ALWAYS provide a complete text timeline.
   The text timeline is the primary deliverable.
   Notion is an optional persistence mechanism, not a replacement.

8. If Notion is configured, follow the Notion instructions below.
   If Notion is unavailable or fails, still provide the full text plan.
   Do not claim that Notion data was saved unless the verified tool
   result confirms persistence.

9. Never mark a task "In Progress" or "Completed" unless
   the campaign input explicitly confirms that status.
   Otherwise, use "Not Started".

10. Use one consistent launch date across the Project Timeline,
    Task List, and Milestones. If the launch is scheduled for
    November 25, all sections must reflect November 25.

REQUIRED OUTPUT FORMAT:

**Project Timeline:**
List all four phases with start dates, end dates, and key activities.

**Task List:**
| Task | Owner | Deadline | Status |
Include actionable tasks covering every campaign phase.

**Budget Breakdown:**
List estimated or provided costs by category and show the total.
Clearly distinguish assumptions from confirmed budget allocations.

**Milestones:**
List important checkpoints with target dates.

**Notion Status:**
State either:
- Project created in Notion, with relevant details, only if confirmed.
- Notion not configured - text timeline only.
- Notion integration failed, with a brief explanation.

{notion_section}
"""



def create_project_manager_agent():
    """Create the Project Manager agent, with Notion MCP if credentials are set."""
    notion_token           = os.getenv("NOTION_TOKEN")
    notion_project_db_id   = os.getenv("NOTION_PROJECT_DATABASE_ID")
    notion_tasks_db_id     = os.getenv("NOTION_TASKS_DATABASE_ID")

    if not notion_token or not notion_project_db_id or not notion_tasks_db_id:
        logger.warning("Notion credentials not set — running without Notion integration")

        return Agent(
            name="project_manager",
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            generate_content_config=GENERATE_CONTENT_CONFIG,
            instruction=get_system_instruction(),
            description=(
                "Project manager for Instagram campaigns. "
                "Creates timelines, task assignments, budgets, "
                "and milestones."
            ),
        )



    else:
        logger.info(
            "Notion configured — projects database: %s, tasks database: %s",
            notion_project_db_id,
            notion_tasks_db_id,
        )

        server_params = StdioServerParameters(
            command="notion-mcp-server",
            args=[],
            env={
                "NOTION_TOKEN": notion_token,
                "PATH": os.environ.get("PATH", ""),
            },
        )

        notion_toolset = McpToolset(
            connection_params=StdioConnectionParams(
                server_params=server_params,
                timeout=30.0,
            )
        )

        return Agent(
            name="project_manager",
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            generate_content_config=GENERATE_CONTENT_CONFIG,
            before_tool_callback=guard_notion_write,
            after_tool_callback=handle_notion_error,
            instruction=get_system_instruction(
                project_database_id=notion_project_db_id,
                tasks_database_id=notion_tasks_db_id,
            ),
            description=(
                "Project manager for Instagram campaigns. "
                "Creates timelines, tasks, budgets, and milestones, "
                "with optional Notion MCP integration."
            ),
            tools=[notion_toolset],
        )



root_agent = create_project_manager_agent()
logger.info("Project Manager agent created")


if __name__ == "__main__":
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    PORT = int(os.getenv("PORT", "8084"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Project Manager on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
