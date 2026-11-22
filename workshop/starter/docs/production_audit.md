
# Production audit — updated 2026-11-23

Project root: `workshop/starter`.

This document records the local hardening work, offline verification,
remaining risks and deployment actions requiring approval.

Latest verified offline test suite: **101 passed, 0 failed**.

No new deployment, IAM modification, Secret Manager change,
or live cloud verification was performed during the final
offline hardening work.


## Confirmed implementation
The Creative Director registers five ReliableRemoteAgent instances through ADK AgentTool, using configured A2A service URLs.
ReliableRemoteAgent extends RemoteA2aAgent and converts remote execution exceptions and error-only events into structured
text responses for the Director's failure-handling callbacks. Specialists run on Cloud Run and Director on Agent Engine.
Strategist researches; Copywriter includes its ADK writing skill; Designer generates image bytes and uploads GCS; Critic
inspects GCS images with Pydantic structured review; PM uses official Notion MCP over stdio with existing-record/query/verification
instructions. Text timeline is primary when Notion fails. Initialization, duplicate prevention,
three total Critic reviews, retries and specialist error handling already exist.
A2A timeout 180s; Director model timeout 120s; image timeout 180s; Cloud Run timeout 300s.
Installed ADK 1.31.1 AgentTool returns merged text for schema-less remote agents and drops error-only
Events; RemoteA2aAgent emits errors for HTTP/connection/initialization failures. Installed genai SDK
already uses bounded exponential backoff with jitter for configured reasoning retries.

## Implemented local hardening
- Added Python session-state guards to block dependent specialist
  operations after a recorded failure.
- Added successful-output retention and completed-request tracking.
- Strengthened Critic response parsing and approval invalidation.
- Enforced three total Critic reviews, including the initial review.
- Added `critic_in_progress` protection against overlapping Critic
  reviews and creative changes during review.
- Added error handling for empty and malformed specialist responses.
- Connected ReliableRemoteAgent to the Creative Director to preserve
  remote errors and transport exception messages.
- Added local Designer replay safeguards and disabled automatic
  retries for billable image generation.
- Added safeguards for repeated Notion write attempts.
- Restricted image review, display and signing to the configured
  GCS bucket.
- Added offline tests, evaluation fixtures and documentation.

These are local implementation safeguards. They do not guarantee
distributed exactly-once execution, durable recovery or deployed
service correctness.

## Security findings requiring cloud-side approval
Deployment source allows unauthenticated Cloud Run invocation and shares one specialist service
identity. It can create Secret Manager versions and IAM grants. Only PM is currently enabled in the
specialist deployment list. Agent Engine source explicitly enables content capture.
No scripts or live policy/secret inspections were run.
Implement/test ID-token A2A transport for card discovery and requests before removing allUsers
run.invoker; grant roles/run.invoker only to Director runtime identity. Use separate identities:
Designer bucket objectCreator, Critic objectViewer, PM secretAccessor on Notion token secret only;
signer objectViewer with Director signBlob permission on that identity only. Review broad roles before
removal. Enable uniform bucket access/public access prevention; remove public object bindings.
Use ADC/workload identities, not downloaded keys. Restrict Notion access to required databases.
Set actual runtime log/trace/session retention and access controls. Local changes do not alter deployments.
Signed URLs expire in one hour, are bearer credentials, and are not permanent Notion attachments.
Do not place raw errors, prompts, tokens or signed URLs in application logs.

## Residual risks
Session caches do not provide durable cross-process or cross-session idempotency. Remote timeouts
can leave operations running. Reconcile objects/pages before recovery; never replay a whole campaign
blindly. Critic syntax cannot prove semantic quality or that all images were reviewed. Untrusted
specialist output/research can contain prompt injection. Cloud auth, IAM, deployed behavior and
production latency remain unverified. Secret-pattern scanning is not a history or cloud secret audit.

The adjacent `reliability.py` module contains specialist lifecycle
helpers (`guard_specialist`, `begin_specialist`, `finish_specialist`)
that are not currently invoked by the Creative Director.
Consequently, their generic specialist serialization and latency
recording behavior must not be treated as active runtime safeguards.
The connected implementation uses the Critic-specific execution
marker and the Director's active callbacks.

## Additional findings during source verification
Critic prompt incorrectly treated NOT_REVIEWED as approval even though Director rejected it; aligned
the prompt with the existing fail-closed gate. Restrict image display/review/signing to the configured
bucket. Director deployment source now passes GCS_IMAGES_BUCKET so the stricter tools remain usable.
Only configuration source was changed; actual deployments retain their existing settings.
Specialist retry files differ (for example Critic has three attempts, Director five); no dependency or
retry-framework changes were made. Full message LoggingPlugin is disabled, but upstream ADK can
still log transport errors/metadata. Review/redact infrastructure logs before production use.

## Final local outcome and exact change inventory

Existing architecture and agent responsibilities remain intact. Reliability code lives beside the
Director; its factory and callback names remain.
The latest full offline pytest suite passed **101 tests with zero
failures**. This includes additional regression tests for Critic
response cleanup and ReliableRemoteAgent wiring.

An earlier verification run recorded five passing offline
evaluation fixtures. That evaluation command has not been
independently rerun as part of the latest test confirmation.

The current verification does not establish live distributed A2A,
Cloud Run, Agent Engine, GCS or Notion correctness.
 See testing.md for commands and warnings.
All changes in this pass are within starter. No files were staged or committed; no cloud resource
was modified, and no package source/dependency versions/lockfiles were changed.

| File relative to starter | Purpose |
|---|---|
| .gitignore | Independent local configuration/session/cache/credential exclusions |
| .env.example | Default message-content capture off |
| README.md | Self-contained business, architecture, setup, testing and limitations guide |
| agents/creative_director/agent.py | Connect session guards/normalization, strengthen gate, preserve existing factory/callbacks |
| agents/creative_director/reliability.py | Isolate remote error adapter, safe response normalization, replay guards and metrics |
| agents/creative_director/prompt.py | Remove conflicting retry/review guidance; treat external content as untrusted |
| agents/creative_director/get_image_links_tool.py | Restrict bucket and fail closed without signing identity |
| agents/creative_director/display_image_tool.py | Restrict displayed images to configured bucket |
| agents/critic/agent.py | Align NOT_REVIEWED prompt with gate rejection |
| agents/critic/image_review_tool.py | Restrict reviewed images to configured bucket |
| agents/designer/image_gen_tool.py | Exact request cache, single generation attempt, input validation and artifact preservation |
| agents/project_manager/agent.py | Guard identical create/append attempts; recognize all HTTP errors; omit raw errors from logs |
| deploy/deploy_orchestrator.py | Pass bucket for stricter tools and disable content capture in future deployment source |
| tests/conftest.py | Disable dotenv/config and prevent outbound network in tests |
| tests/test_hardening.py | Failure, ambiguity, replay, security/input and artifact regressions |
| tests/test_runner_offline.py | Real local ADK Runner with scripted models and fake specialists |
| tests/test_evaluation.py | Fixture expectations, denominators and latency aggregation |
| evaluation/offline.py | Deterministic callback regressions and local state aggregation CLI |
| evaluation/cases.json | Five reproducible regression scenarios |
| docs/architecture.md | Mermaid diagram, execution flow and session boundaries |
| docs/production_audit.md | Confirmed findings, risks, fix inventory and completion estimates |
| docs/testing.md | Test layers, commands, metric definitions and actual final results |
| docs/deployment.md | Setup, existing entry points, cloud approval actions and recovery |
| docs/demo_script.md | Six-minute technical demo |

Pre-existing changes to Strategist, Copywriter, Designer agent declarations, deployment selection,
pyproject and lockfiles were preserved. Existing tests were not rewritten. The one-line Critic prompt
correction and image-review bucket boundary are intentional changes to previously modified files.
A temporary pre-edit ZIP snapshot exists outside the project for precise rollback; it contains only
source/config-example files and was not staged.


## Capstone readiness assessment

| Area | Current status | Remaining work |
|---|---|---|
| Architecture and agent responsibilities | Implemented locally | Verify distributed deployment |
| Quality gate and failure handling | Verified by offline tests | Validate live A2A failure scenarios |
| Offline automated tests | 101 passing | Maintain regression coverage |
| Remote error adapter | Implemented and tested offline | Validate deployed transport behavior |
| Side-effect safeguards | Session-level protections implemented | Add durable idempotency and reconciliation |
| Cloud authentication and IAM | Risks documented | Implement and validate approved security changes |
| Evaluation and observability | Offline fixtures available | Collect real runtime measurements |
| Documentation | Updated for current implementation | Final owner review |
| Demo | Script prepared | Rehearse and record |
| Production readiness | Not certified | Complete security and integration validation |

## Explanation for the project owner
If Designer fails, the Director cannot carry on to Critic/PM as though images exist. If captions change
after approval, the old approval is removed and the Critic must review again. If Notion or the timeline
fails, completed captions and image URIs remain in session state. The third rejected review stops the
campaign as unapproved drafts, and a fourth review cannot run. Identical image/write attempts are
blocked or cached locally; a timeout still needs reconciliation because remote work may have finished.
