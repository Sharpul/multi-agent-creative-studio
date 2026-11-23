# Multi-Agent Creative Studio

Create an Instagram campaign from one brief: audience research, three captions, generated images,
quality review and a project timeline, with optional Notion persistence. This directory is the project
root: run commands here and keep configuration, tests, evaluation and documentation here.

## Business problem and value
Campaign creation crosses several disciplines. Manual handoffs lose context, revisions repeat work,
and approved assets are often separated from the launch plan. This application carries the brief and
specialist results through the same workflow, makes review explicit, and preserves useful work when
optional planning/persistence fails. No productivity or production success-rate measurements are claimed.

## Why multiple agents
Research, writing, image generation, review and project planning need different prompts and tools.
Separately hosted specialists support independent scaling and tool permissions. The Creative Director
coordinates them over A2A; the Project Manager accesses Notion tools through MCP. The extra network
boundaries also introduce latency, failure and idempotency risks, covered in the audit.

| Agent | Responsibility |
|---|---|
| Creative Director | Classify requests, initialize campaigns, carry context, route work and enforce approval |
| Brand Strategist | Search-backed audience, competitor and trend research |
| Copywriter | Three Instagram caption variations using its local ADK skill |
| Designer | Gemini image generation and GCS upload |
| Critic | Posts review and real-image review with explicit verdicts |
| Project Manager | Text timeline, tasks, budget and milestones; optional Notion persistence |

## Workflow and protocols
Initialize once ? research ? captions ? images ? Critic ? revisions when needed ? approval ? timeline.
The Director wraps ReliableRemoteAgent instances in ADK AgentTools.ReliableRemoteAgent extends RemoteA2aAgent to preserve remote error
events and convert transport exceptions into structured error responses. Specialist URLs identify independent Cloud Run
services; Agent Engine hosts the Director. Each call must carry the necessary brief/upstream outputs.
MCP exposes Notion schemas/query/create/retrieve tools to PM via its stdio server.
See the [architecture diagram and state boundaries](docs/architecture.md).

Both posts and visuals must be APPROVED and All Approved must be YES. Missing, duplicate, contradictory
or NOT_REVIEWED verdicts fail closed. **Three total Critic reviews** include the initial review and at
most two re-reviews. Changing creative inputs invalidates approval. The fourth review is blocked.

## Reliability and side effects
- Session guards block dependent specialist calls after failure.
- The Critic in-progress marker prevents overlapping Critic reviews and blocks creative revisions during review.
- These session-state checks are not atomic distributed locks and do not guarantee cross-worker concurrency protection.
- Actual remote error messages survive ADK's error-only Event/text boundary.
- Completed specialist outputs remain in session state if later steps fail.
- Reasoning retains bounded SDK retries with exponential backoff/jitter; A2A calls are not blindly replayed.
- Billable image generation uses one SDK attempt. Identical image requests use a local session cache.
- Identical Designer requests, repeated PM invocations and identical Notion create/append attempts are guarded.
- Image signing/display/review is restricted to GCS_IMAGES_BUCKET. Links expire after one hour.

These controls are session safeguards, not durable distributed exactly-once processing. A timeout may
mean an operation completed remotely. Reconcile existing images/pages/tasks before recovery in a new
session. Never rerun the whole campaign just because Notion or link signing failed.

## Local setup
Use Python 3.12 for the demonstrated environment (`pyproject.toml` permits Python >=3.11), uv and the
existing virtual environment. Copy `.env.example` to `.env`; fill project, model location, Cloud Run
region, image bucket and specialist URLs. Use ADC locally and attached workload identities in cloud.
Notion is optional: configure token plus both database IDs and install the official notion-mcp-server
on PATH in an approved runtime. Do not commit credentials.

For a new checkout, dependency installation with `uv sync --dev` requires network access and changes
an environment. No installation/dependency update was performed in this hardening pass. For this
existing checkout, use frozen/no-sync commands below. Live use requires an explicitly approved cloud
project, identity and budget. See [deployment and configuration](docs/deployment.md).

## Offline tests and evaluation
Run from this directory:

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'creative-studio-uv-cache'
uv run --frozen --no-sync python -m pytest tests -q -p no:cacheprovider
uv run --frozen --no-sync python evaluation/offline.py
```
### Latest verification

- Google ADK version: 1.31.1
- Python version: 3.12.10
- Full offline pytest suite: 101 passed, 0 failed
- Additional regression coverage includes empty Critic response cleanup
  and static verification of ReliableRemoteAgent callback wiring.
- **Deployed A2A integration:** The distributed workflow has been validated 
  through a campaign executed on Vertex AI Agent Engine, communicating with 
  specialist agents     deployed on Cloud Run. The execution demonstrated 
  remote A2A communication, image generation and GCS storage, Critic feedback, 
  Designer revisions, and enforcement of the quality-gate limit. The campaign 
  was safely stopped without Project Manager execution when approval was not obtained.

Tests use fakes/mocks, disable developer dotenv configuration and block external socket connections.
They include actual local ADK Runner dispatch with scripted models; they do not prove distributed
A2A or deployed cloud behavior. Evaluation rates come from deterministic fixtures, not production
campaigns. [Testing and metric definitions](docs/testing.md) explains the exact scope.

## Deployment and known limitations
Specialists run on Cloud Run; Director runs on Vertex AI Agent Engine; GCS stores private images;
PM uses optional Notion MCP. Deployment entry points are under `deploy/` and can change secrets/IAM
and create billable resources. Do not execute them without approval.
Current production blockers include public Cloud Run invocation, a shared specialist identity,
non-durable side-effect guards, prompt injection risks and expiring Notion image links. The deployment 
configuration includes all five specialist agents: Brand Strategist, Copywriter, Designer, Critic, and 
Project Manager. The deployment scripts collect Cloud Run service URLs and pass them to the Creative 
Director on Vertex AI Agent Engine.. Model defaults vary across code/config; select a supported model and
region explicitly. Existing deployments have not been changed or validated.

- [Architecture](docs/architecture.md)
- [Production audit, security actions and change inventory](docs/production_audit.md)
- [Testing and offline evaluation](docs/testing.md)
- [Deployment and recovery](docs/deployment.md)
- [Six-minute demo](docs/demo_script.md)
