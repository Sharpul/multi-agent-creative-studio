# Testing and evaluation

All commands run from `starter`. No live Gemini, Vertex AI, Cloud Run, GCS or Notion calls are required.

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'creative-studio-uv-cache'
uv run --frozen --no-sync python -m pytest tests -q -p no:cacheprovider
uv run --frozen --no-sync python evaluation/offline.py
```

Frozen/no-sync prevents environment/lockfile changes. The cache override avoids a Windows uv cache
permission issue; disabling pytest cache avoids an existing directory permission warning. The plain
requested command `uv run python -m pytest tests -q` can also be run with UV_NO_SYNC=1, UV_FROZEN=1
and PYTEST_ADDOPTS='-p no:cacheprovider' to preserve this same environment.

## Test layers
| Layer | Files / scope |
|---|---|
| Unit | test_quality_gate.py; response parsing, image replay, URI boundaries and MCP error tests in test_hardening.py |
| Callback integration | Existing lifecycle/gate tests plus revision, exhaustion, stale approval, failure latch and retained-output tests |
| ADK orchestration integration | test_runner_offline.py executes a real Runner, scripted BaseLlm and AgentTool dispatch with local fake specialists |
| Remote adapter boundary | Injects ADK error Events/raised exceptions; checks exact timeout/connection/429/500/503 messages |
| Offline evaluation | test_evaluation.py checks fixtures, denominators, failure categories and latency aggregation |
| Critic lifecycle regression | `test_hardening.py`; parallel review blocking, empty-response cleanup and transport-failure handling |
| Static wiring verification | `test_hardening.py`; checks ReliableRemoteAgent construction and ADK callback configuration |

The Runner scenarios deliberately request PM before approval, a fourth review and dependent work after
failure; assertions verify the specialist was not invoked. PM failure preserves approved captions.
HTTP cases inject errors, not actual HTTP servers. No distributed A2A/cloud integration or live
creative-quality evaluation has been performed.

`conftest.py` disables dotenv, clears remote/Notion configuration before app imports and blocks outbound
Python socket connections. Windows asyncio's internal socketpair is allowed only during construction.
Service clients are mocked. No application environment or credentials need copying into tests.

## Evaluation definitions
`evaluation/cases.json` contains success, revision, exhaustion, specialist failure and PM failure cases.
The CLI runs callbacks directly with fake response fixtures and checks expected outcome, review count
and blocked-call count; it exits nonzero on regression. These fixture outcomes are not production
performance or content-quality measurements.

- Campaign completion success rate: approved, no specialist failure, and all five specialist outputs
  present, divided by initialized campaign states.
- Critic approval rate: campaigns with final approval divided by campaign states, not approvals per review.
- Average review count: total recorded Critic reviews divided by campaigns, including campaigns with zero.
- Specialist failure rate: failed executed specialist calls divided by executed calls; blocked calls excluded.
- Failure categories: specialist failure, PM failure, exhausted reviews, incomplete or none.
- Mean specialist latency: mean of available nonnegative tool-duration samples; sample count is reported.
  Offline fixture timings are deliberately omitted. Missing/zero denominators return null.


**Implementation note:** The `specialist_metrics` recording logic
in `reliability.py` is not currently connected to the active
Creative Director callbacks. Latency aggregation supports supplied
samples, but automatic specialist latency collection through
that helper is not active.

To aggregate locally exported ADK state objects without cloud requests:

```powershell
uv run --frozen --no-sync python evaluation/offline.py --states path/to/session_states.json
```

Input is a JSON array of state objects, not complete event/session envelopes. One terminal state per
campaign avoids double counting. Exports may contain user material and errors: keep them private and
out of version control. Aggregation quality depends on supplied data and is not independent verification.

## Static verification
No lint/formatter/type-checker is configured. AST parsing checks Python syntax without installing tools
or modifying dependencies. `git diff --check` checks whitespace; existing unrelated changes are reported
separately. Dependency warnings are retained rather than suppressed: ADK experimental features and
AgentTool's nested Runner deprecated plugins parameter. Installed package source is never edited.


## Recorded verification — 2026-11-22

### Latest offline test results

- Original hardening baseline: 78 passed, 21 failed.
- Latest full suite: **101 passed, 0 failed**.
- Python version: 3.12.10.
- Google ADK version: 1.31.1.
- Command executed:

  `uv run python -m pytest tests/ -q --tb=short`

- The latest changes were verified using offline tests.
  No live Gemini, Vertex AI, Cloud Run, GCS or Notion calls
  were required.

### Additional regression coverage

- Critic review exhaustion and approval enforcement.
- Specialist failure detection and dependency blocking.
- Empty Critic response releases the execution marker.
- Critic transport failure does not count as a review.
- Duplicate Designer and Project Manager execution guards.
- Parallel Critic execution protection.
- ReliableRemoteAgent error-event preservation.
- Static verification of ReliableRemoteAgent constructor
  and callback wiring.

### Remaining verification limitations

- The latest full-suite run was not a deployed A2A test.
- Distributed concurrency and cross-session idempotency
  are not guaranteed.
- Cloud Run and Agent Engine behavior after the latest
  hardening changes has not been revalidated.
- Actual campaign latency, creative quality and
  production success rates have not been measured.

### Earlier audit evidence

The November 17 audit also recorded:

- Five offline evaluation fixtures passing.
- AST syntax parsing of 37 Python files.
- A heuristic credential scan with zero flagged files.
- One pre-existing trailing whitespace issue in
  deploy_all_specialists.py.
- No deployments, commits or dependency updates during
  that earlier audit.

These earlier checks have not all been rerun as part
of the latest verification.
