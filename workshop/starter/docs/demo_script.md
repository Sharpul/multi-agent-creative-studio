# Six-minute technical demonstration

Prepare a previously captured successful campaign: brief, research, three captions, generated images,
Critic verdict, timeline and optional Notion screenshot. Identify captured material explicitly.
Run offline commands from `starter`; live service use requires separate approval.

| Time | Demonstration |
|---|---|
| 0:00–0:45 | Explain the business problem: campaign creation requires research, writing, design, review and planning, with repeated manual handoffs |
| 0:45–1:30 | Show the architecture diagram: Creative Director, five A2A specialists, Gemini, GCS and optional Notion MCP |
| 1:30–2:30 | Walk through an existing captured campaign, if available: brief, research, three captions and generated images. Clearly distinguish captured live outputs from offline fixtures |
| 2:30–3:30 | Explain the Critic approval gate, rejected verdicts, revision handling and maximum three reviews |
| 3:30–4:30 | Show the 101 passing offline tests and explain the local ADK Runner scenarios: blocked PM, exhausted review budget and failure propagation |
| 4:30–5:15 | Show the offline evaluation fixtures and explain why fixture success rates are not production performance metrics |
| 5:15–6:00 | Demonstrate retained outputs after failure, explain replay safeguards and acknowledge remaining cloud security and distributed recovery work |


Commands:

```powershell
$env:UV_CACHE_DIR = Join-Path $env:TEMP 'creative-studio-uv-cache'
uv run --frozen --no-sync python -m pytest tests -q -p no:cacheprovider
uv run --frozen --no-sync python evaluation/offline.py
```


## Verification evidence

The latest confirmed offline test run completed with:

- **101 tests passed**
- **0 test failures**
- Google ADK 1.31.1
- Python 3.12

The suite includes local ADK Runner integration tests, quality-gate
regressions, specialist error handling and ReliableRemoteAgent
wiring verification.

These results do not establish live Cloud Run, Agent Engine or
distributed A2A correctness.

The offline evaluation CLI should be executed separately before
recording to confirm its current results.


Closing explanation:
The Creative Director orchestrates five specialist agents responsible for research, copywriting, design, quality review and project planning.

Rather than relying only on LLM instructions, I implemented Python-based quality gates to enforce approval requirements, limit review attempts and prevent dependent operations after failures.

The system also preserves completed work and includes safeguards against repeated billable operations.

I validated these behaviors using 101 passing offline tests, including local Google ADK orchestration tests.

The remaining work before production deployment includes authenticated A2A communication, stricter cloud IAM, durable idempotency and live distributed integration testing.
