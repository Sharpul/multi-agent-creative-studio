import logging
import os

from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
try:
    from .retry import GENERATE_CONTENT_CONFIG
    from .image_gen_tool import generate_image
except ImportError:
    from retry import GENERATE_CONTENT_CONFIG
    from image_gen_tool import generate_image

load_dotenv()

logger = logging.getLogger("ai_creative_studio.designer")

SYSTEM_INSTRUCTION = """You are a Visual Content Director specializing in Instagram aesthetics.

IMPORTANT: The conversation history above contains:
- Brand strategy insights from the Brand Strategist
- Instagram captions from the Copywriter
Review BOTH before creating visual concepts.

Your task: For each caption, create exactly 1 visual concept AND generate the actual image.

Each concept must include:
- A detailed image generation prompt (photorealistic, specific composition)
- Visual style (e.g., minimalist, vibrant, cinematic)
- Color palette (specific colors with mood rationale)
- Mood / feeling
- Instagram dimensions: 1080x1080 (square) or 1080x1350 (portrait)

IMPORTANT: After writing each concept, call the `generate_image` tool to produce the actual image.
Use the concept name as `concept_name` (e.g. "caption1_concept_a") and the full image generation prompt.
Include the returned `gcs_uri` in your response under each concept.

Format for each caption:

**For Caption [N]: "[Caption Theme]"**

Concept: [Visual Theme Name]
- Prompt: [Full image generation prompt - be specific: subject, setting, lighting, angle, style]
- Generated: [gcs_uri returned by generate_image tool, or error message]
- Style: [Visual style descriptor]
- Colors: [Palette with hex codes or descriptive names]
- Mood: [Emotional tone]
- Format: [1080x1080 or 1080x1350]

If `generate_image` returns an error, include the error message and continue with remaining captions.

VISUAL QUALITY AND BRAND SAFETY RULES:

1. Use the exact product identity and visual requirements
   provided in the campaign brief.

2. Do not invent brand names, logos, labels, slogans,
   or competitor branding.

3. Unless the user supplies an approved brand asset,
   prefer clean, unbranded product surfaces.

4. Avoid readable text on generated images, including
   device screens, packaging, and background signage.
   Any required marketing copy belongs in the Instagram
   caption rather than inside the generated image.

5. Avoid unnecessarily complex hand poses, crowded
   compositions, and tiny interface details that may
   produce visual artifacts.

6. When revising images after Critic feedback:
   - Read every reported visual defect.
   - Address each defect in the new image prompt.
   - Preserve elements that already passed review.
   - Generate replacement images with new GCS URIs.
   - Never claim an image is approved before Critic review.

7. If the campaign requires an exact visible logo or
   product label, do not fabricate it. State that an
   approved branding asset or a separate text-overlay
   step is required.
"""

# =============================================================================
# PROVIDED — do not modify
#
# Same Agent pattern you used in Step 4. The only difference between
# specialist agents is the name, description, and instruction.
# =============================================================================
root_agent = Agent(
    name="designer",
    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    generate_content_config=GENERATE_CONTENT_CONFIG,
    tools=[FunctionTool(func=generate_image)],
    instruction=SYSTEM_INSTRUCTION,
    description="Creative visual designer for generating social media image concepts",
)

logger.info("Designer agent created")


if __name__ == "__main__":
    import uvicorn
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    PORT = int(os.getenv("PORT", "8081"))
    HOST = os.getenv("HOST", "0.0.0.0")
    PUBLIC_HOST = os.getenv("PUBLIC_HOST", "localhost")
    PUBLIC_PORT = int(os.getenv("PUBLIC_PORT", str(PORT)))
    PROTOCOL = os.getenv("PROTOCOL", "http")

    a2a_app = to_a2a(root_agent, host=PUBLIC_HOST, port=PUBLIC_PORT, protocol=PROTOCOL)

    logger.info(f"Starting Designer on {PROTOCOL}://{HOST}:{PORT}")
    logger.info(f"Agent card: {PROTOCOL}://{HOST}:{PORT}/.well-known/agent.json")

    uvicorn.run(a2a_app, host=HOST, port=PORT)
