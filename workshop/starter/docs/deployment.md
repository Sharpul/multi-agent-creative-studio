# Setup, deployment and recovery

Project root: this `starter` directory. No deployment, IAM change, Secret Manager modification,
image generation, Notion write or live cloud verification was performed during hardening.

## Configuration
Copy `.env.example` to `.env` locally and fill:

| Variable | Purpose |
|---|---|
| GOOGLE_CLOUD_PROJECT | Vertex AI/GCS project |
| GOOGLE_CLOUD_PROJECT_NUMBER | Existing Agent Engine deployment/signing configuration |
| GOOGLE_CLOUD_LOCATION | Model routing location; may be global for supported models |
| CLOUD_RUN_REGION | Real regional Cloud Run/Agent Engine location |
| GEMINI_MODEL / GEMINI_IMAGE_MODEL | Explicit available reasoning/image models |
| GCS_IMAGES_BUCKET | Private bucket, required for generation/review/display/signing |
| SIGNING_SERVICE_ACCOUNT | Signing identity when runtime ADC does not supply one |
| *_AGENT_URL | Strategist/copywriter/designer/critic/PM A2A services |
| NOTION_TOKEN + both database IDs | Optional MCP persistence |
| AGENT_ENGINE_ID / resource name | Existing deployed Director |

Use Python 3.12, uv and the existing environment. New installations require network access and approved
installation via `uv sync --dev`; this pass did not sync dependencies. Use ADC locally and attached
workload identity in cloud. Avoid private-key files. Notion MCP server must be on PATH; the existing PM
Dockerfile installs its official npm package. Model defaults vary across code/example/deployment source;
choose an available model and compatible location explicitly before approved use.

For approved interactive local use: `uv run --frozen --no-sync adk web agents`. Starting a local UI
is different from authorizing live interaction; submitting a campaign can invoke billable services.
`run_campaign.py` immediately connects to an existing Agent Engine and runs a campaign: do not import
or execute it as an offline check.

## Existing deployment entry points
- `deploy/deploy_all_specialists.py`: builds/deploys Cloud Run, may add Secret Manager versions/IAM
  bindings, and writes service URLs to .env. The deployment script currently selects only the Project Manager
  for deployment; the other specialists are commented out. This is a deployment-script configuration, not evidence that
  the other services are currently running or have been validated. All five specialist URLs must resolve to compatible A2A
  services for the complete distributed workflow to operate. Review the intended selection before an approved deployment.
  No list changes were made.
- `deploy/deploy_orchestrator.py`: creates Agent Engine, packages the Director and passes configuration.
  Source now passes GCS_IMAGES_BUCKET and disables content capture; existing deployed settings are
  unaffected. Existing deployment dependency specifications were preserved.
- `deploy/teardown_gcp.sh`: destructive cloud teardown, not part of verification.

A2A timeout 180s is shorter than Cloud Run 300s and possible repeated model call budgets. A local
timeout can leave a remote write/generation running. Do not solve this by replaying the operation.

## Cloud changes requiring explicit approval
1. Implement/test ID-token authentication for A2A requests AND agent-card discovery. Then remove
   allUsers run.invoker and grant roles/run.invoker only to Director runtime identity. Current source
   deploys --allow-unauthenticated; switching flags without token transport breaks the application.
2. Split the shared specialist identity. Grant Designer bucket objectCreator, Critic objectViewer,
   PM secretAccessor on its token secret only. Signing identity needs objectViewer; Director needs
   signBlob on that identity only. Review current IAM before removing existing broad grants.
3. Enable uniform bucket-level access and public access prevention; remove public object bindings.
4. Restrict the Notion integration to the required databases; use Secret Manager with deliberate
   token rotation/versioning rather than adding versions on every deploy without review.
5. Disable content capture in ACTUAL runtime settings, restrict trace/session/log access and define
   retention. Removing full LoggingPlugin does not remove all SDK/transport logs.
6. Verify model availability, quotas/cost budget, runtime service identity and request concurrency.
   The current `critic_in_progress` session marker guards overlapping
   Critic reviews and creative changes during review. It does not
   serialize all specialist operations or provide a distributed lock
   across concurrent invocations.


Signed image URLs last one hour. Keep canonical GCS URIs as durable references and regenerate access
links through an authorized signing identity; do not make buckets public to repair expired Notion links.

## Failure recovery
Preserve outputs and IDs before changing sessions. After uncertain generation or writes, inspect existing
GCS objects and query Notion project/task records with owner approval. Reuse completed artifacts; never
retry the whole workflow to repair a missing timeline/link. Identical session attempts are guarded,
but caches cannot prevent duplication across restarts, remote sessions or changed arguments.
A separate reviewed recovery path is required before production automation can resume uncertain work.
Rollback would select a reviewed previous Cloud Run/Agent Engine revision; it was not executed/tested.


If a Critic operation is interrupted outside the handled response lifecycle, its session marker may remain set. Inspect the session
state and remote operation outcome before attempting recovery. Do not clear the marker or replay the review automatically without
confirming that doing so is safe.
