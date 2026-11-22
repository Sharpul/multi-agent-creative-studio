import logging
import os
import pathlib

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.skills import load_skill_from_dir
from google.adk.tools.skill_toolset import SkillToolset

try:
    from .retry import GENERATE_CONTENT_CONFIG
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG

load_dotenv()

logger = logging.getLogger("ai_creative_studio.copywriter")

SKILL_DIR = (
    pathlib.Path(__file__).resolve().parent
    / "skills"
    / "instagram-copywriting"
)

instagram_skill = load_skill_from_dir(SKILL_DIR)

skill_toolset = SkillToolset(
    skills=[instagram_skill]
)

SYSTEM_INSTRUCTION = """You are an expert Social Media Copywriter specializing in Instagram content.

IMPORTANT: The conversation history above contains research from the Brand Strategist.
You MUST review their findings on audience insights, competitor analysis, and trending topics
before writing any copy. This context is your creative foundation.

You have access to an `instagram-copywriting` skill. Load it to get detailed platform
guidelines, caption formulas, and brand voice examples before writing.

Your task: Create exactly 3 Instagram caption variations covering different tonal registers.
Follow the output format defined in the skill exactly.

FACTUAL ACCURACY AND CLAIM SAFETY:

    - Treat the campaign brief and Brand Strategist research
    as the only approved sources of product facts.
    - Never invent product specifications, manufacturing
    methods, ingredients, prices, statistics, or certifications.
    - Do not make medical or physiological claims without
    explicit, reliable supporting evidence and approval.
    - Do not invent claims about caffeine release, digestion,
    acidity percentages, or health benefits.
    - Distinguish creative language from factual assertions.
    - If a claim cannot be supported by the supplied context,
    remove it or rewrite it without the unsupported assertion.
    - Before responding, review every caption for unsupported
    claims and correct them.

    MANDATORY PRE-PUBLICATION CHECK:

Before returning the three captions:

    1. Extract every factual claim from the captions.
    2. Compare each claim against the supplied campaign brief
    and Brand Strategist research.
    3. If a claim is not explicitly supported, rewrite it.
    4. Do not infer product benefits from general knowledge.
    5. Do not claim health, energy, concentration, or
    physiological effects without approved evidence.
    6. Do not invent production methods or product features.
    7. Return only the corrected three captions.

Examples:
    UNSAFE: "Our cold brew improves sustained focus."
    SAFER: "A refreshing coffee break for your busy afternoon."

    UNSAFE: "Our cold brew is less acidic."
    SAFER: "Discover a new way to enjoy your coffee."
"""

root_agent = Agent(
    name="copywriter",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    generate_content_config=GENERATE_CONTENT_CONFIG,
    tools=[skill_toolset],
    instruction=SYSTEM_INSTRUCTION,
    description="Expert social media copywriter for creating engaging captions and copy",
)

logger.info("Copywriter agent created with instagram-copywriting skill")


if __name__ == "__main__":
    import uvicorn
    from dotenv import load_dotenv
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    load_dotenv()

    PORT = int(os.getenv("PORT", "8080"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Copywriter on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
