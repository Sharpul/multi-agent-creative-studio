
"""Gemini native image generation tool. Generates image, uploads to GCS, returns URI."""

import hashlib
import json
import re
import io
import os
import uuid

from google import genai
from google.adk.tools import ToolContext
from google.cloud import storage
from google.genai import types


async def generate_image(
    concept_name: str,
    image_prompt: str,
    aspect_ratio: str,
    tool_context: ToolContext,
) -> dict:
    """
    Generate an image with Gemini and upload it to GCS.

    Args:
        concept_name: Identifier, e.g. "post1_concept_a"
        image_prompt: Detailed image generation prompt
        aspect_ratio: "1:1" or "4:5"

    Returns:
        {"status": "success", "gcs_uri": "...", "concept_name": "..."}
        or {"status": "error", "error": "..."}
    """

    if not isinstance(concept_name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", concept_name):
        return {"status": "error", "error": "concept_name must use 1-128 letters, digits, underscores or hyphens"}
    if not isinstance(image_prompt, str) or not image_prompt.strip():
        return {"status": "error", "error": "image_prompt is required"}

    bucket_name = os.environ.get("GCS_IMAGES_BUCKET")
    if not bucket_name:
        return {
            "status": "error",
            "error": "GCS_IMAGES_BUCKET env var not set",
        }

    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
    image_model = os.environ.get(
        "GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image"
    )

    if not project_id:
        return {
            "status": "error",
            "error": "GOOGLE_CLOUD_PROJECT env var not set",
        }

    if aspect_ratio not in ("1:1", "4:5"):
        return {
            "status": "error",
            "error": "aspect_ratio must be '1:1' or '4:5'",
        }

    aspect_hint = {
        "1:1": "square 1:1 aspect ratio (1080x1080)",
        "4:5": "portrait 4:5 aspect ratio (1080x1350)",
    }[aspect_ratio]

    prompt_with_aspect = (
        f"{image_prompt}\n\n"
        f"Generate this as a {aspect_hint} image."
    )

    key = hashlib.sha256(json.dumps(
        [project_id, bucket_name, image_model, concept_name, image_prompt, aspect_ratio]
    ).encode()).hexdigest()
    operations = dict(tool_context.state.get("image_operations", {}))
    if key in operations:
        return operations[key]
    operations[key] = {
        "status": "error", "error": "Image operation already attempted; outcome may be unknown",
        "recovery_hint": "Reconcile existing GCS objects before any new generation attempt.",
    }
    tool_context.state["image_operations"] = operations

    try:
        client = genai.Client(
            vertexai=True,
            project=project_id,
            location=location,
        )

        response = client.models.generate_content(
            model=image_model,
            contents=prompt_with_aspect,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"],
                http_options=types.HttpOptions(
                    retry_options=types.HttpRetryOptions(
                        attempts=1,  # Generation may be billable even when its response times out.
                        exp_base=2,
                        initial_delay=30,
                        http_status_codes=[429, 500, 503, 504],
                    ),
                    timeout=180_000,
                ),
            ),
        )

        image_bytes = None
        mime_type = "image/png"

        if response.candidates:
            candidate = response.candidates[0]

            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.inline_data is not None:
                        image_bytes = part.inline_data.data
                        mime_type = (
                            part.inline_data.mime_type or "image/png"
                        )
                        break

        if not image_bytes:
            return {
                "status": "error",
                "error": "Gemini returned no image data",
            }

        ext = "jpg" if "jpeg" in mime_type else "png"

        storage_client = storage.Client(project=project_id)
        bucket = storage_client.bucket(bucket_name)

        blob_name = (
            f"campaign-images/"
            f"{concept_name}-{uuid.uuid4().hex[:8]}.{ext}"
        )

        blob = bucket.blob(blob_name)

        blob.upload_from_file(
            io.BytesIO(image_bytes),
            content_type=mime_type,
        )

        gcs_uri = f"gs://{bucket_name}/{blob_name}"

        result = {"status": "success", "gcs_uri": gcs_uri, "concept_name": concept_name}
        operations[key] = result
        tool_context.state["image_operations"] = operations
        try:
            artifact = types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            )

            await tool_context.save_artifact(
                f"{concept_name}.{ext}",
                artifact,
            )

        except ValueError:
            # Artifact service may not be configured
            pass

        return result

    except Exception as e:
        if operations[key].get("status") == "success":
            # GCS upload succeeded. Artifact rendering must not cause regeneration.
            result = {**operations[key], "artifact_warning": str(e)}
        else:
            result = {"status": "error", "error": str(e),
                      "recovery_hint": "Outcome may be unknown. Reconcile GCS before retry."}
        operations[key] = result
        tool_context.state["image_operations"] = operations
        return result
