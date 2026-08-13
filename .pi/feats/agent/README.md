# Agent Layer

Local-inference features for the CRM. Disabled by default — turn on in
**CRM Agent Settings** after pointing `base_url` at an OpenAI-compatible endpoint.

## Layers

| Module | Responsibility |
|---|---|
| `config.py` | Reads `CRM Agent Settings` into an `AgentConfig` |
| `schemas.py` | Output models; one source for the guided-decoding schema and validation |
| `context.py` | Prompt construction; fences untrusted text as data |
| `client.py` | OpenAI-compatible call, one validation retry, `AgentUnavailable` on failure |
| `tools.py` | The capability layer — permission-checked reads only |
| `api.py` | Whitelisted endpoints; returns `ok` / `disabled` / `unavailable` |
| `install.py` | Idempotent `CRM Agent` role, run from `after_install` + `after_migrate` |

Import direction is one-way: `errors` ← `config`/`schemas`/`context` ← `client` ←
`tools`/`api`. No module imports one to its right.

## Rules

- Reads go through `frappe.get_list`, never `ignore_permissions`.
  `tests/test_tools.py` enforces this by parsing the module's own AST against an
  **allowlist** of the `frappe.*` calls `tools.py` may make, so the invariant cannot
  erode quietly.
  One documented exception: `read_thread` fetches a record's `Communication` rows with
  `frappe.get_all`, gated on a permission-checked read of the parent record first and
  hard-scoped to that parent. frappe's own `permission_query_condition` for
  `Communication` keeps only rows belonging to the reading user's email accounts, so
  `get_list` returned an empty thread for every ordinary CRM user while the endpoint
  still reported `ok`. Authority for a child read comes from its parent — the same
  shape frappe's `get_docinfo` timeline uses. Adding a second exception means adding
  to the allowlist, in review.
- The model is configuration: base URL plus model name. No prompt or parser may be
  model-specific — swapping models must not require a code change.
- Communication bodies are untrusted. They are fenced, the system prompt states that
  fenced text is data rather than instructions, and this layer holds no write tools
  that hostile content could aim at.
- The endpoint degrades: with the flag off or the endpoint down, callers get a status,
  never an exception. Config normalisation degrades too — an uninterpretable value falls
  back to its default rather than raising out of `get_config()`.
- Every endpoint that can trigger an outbound model call is `@rate_limit`-ed per user,
  the same rule `crm/domain_enrichment/api.py` follows. One call can hold a worker for
  `timeout × MAX_ATTEMPTS`.
- The role grants no DocPerms yet, on purpose: `add_permission` would snapshot standard
  perms into `Custom DocPerm` on shared core doctypes, irreversibly. See the docstring in
  `install.py`.
- Import direction is enforced, not just documented: `tests/test_layering.py` parses each
  module and fails on a dependency the layering map does not allow, and on any `frappe`
  import reaching the two pure modules (`errors`, `context`).
- Email bodies are stripped of HTML in `tools.read_thread`, not in `context.py` — the
  prompt builder takes plain rows and imports nothing, which is what keeps it testable
  with no site.
- `api_key` is optional. Set it only if the inference server was started with one; blank
  means no `Authorization` header is sent.

## Editing the Settings doctype

Bump `modified` in `crm_agent_settings.json` whenever you change its fields. Frappe
compares that timestamp when deciding whether to re-import the definition, so a field
added without bumping it may be silently skipped on `bench migrate`.

## Running the tests

```bash
cd /workspace/frappe-bench
for m in test_settings test_config test_schemas test_client test_context test_tools test_api test_install; do
  PYTHONPATH=/workspace bench --site dev.localhost run-tests --app crm --module "crm.agent.tests.$m" || break
done
```

`--module` takes one dotted module. **Do not pass the package** (`crm.agent.tests`): the
loader imports the empty `__init__.py`, discovers nothing, and exits `0` without running
a single test or printing a summary — a false green, verified. `--app crm` (the whole
app) works and is what CI runs (`.github/actions/run-server-tests`).

`PYTHONPATH=/workspace` is required in this devcontainer — the bench's `apps/crm` is a
separate checkout, so without it the runner tests that copy rather than the working
tree. No test contacts a model or the network.

## Verifying against a real model

Nothing in the suite talks to a model. `tests/test_client_over_http.py` proves the wire
against a stub OpenAI-shaped server on loopback — URL, headers, guided-decoding body,
retry, and every failure mode — but a stub is not a model. These steps are the part that
needs a GPU, and they are the exit gate for the foundation.

```bash
# 1. Serve the smallest test model. ~5.4 GB in BF16, fits the free VRAM alongside a desktop.
vllm serve LiquidAI/LFM2.5-2.6B --enable-prefix-caching --max-model-len 8192
#    Ollama is the shorter path if vllm is not installed:  ollama serve && ollama run lfm2.5:2.6b

# 2. Point the CRM at it. Name must match what GET /v1/models reports.
cd /workspace/frappe-bench
bench --site dev.localhost set-value "CRM Agent Settings" "CRM Agent Settings" base_url "http://127.0.0.1:8000/v1"
bench --site dev.localhost set-value "CRM Agent Settings" "CRM Agent Settings" model "LiquidAI/LFM2.5-2.6B"
bench --site dev.localhost set-value "CRM Agent Settings" "CRM Agent Settings" enabled 1

# 3. Summarise a real Deal that has Communications on it.
bench --site dev.localhost execute crm.agent.api.summarise_thread \
  --kwargs "{'reference_doctype': 'CRM Deal', 'reference_name': 'CRM-DEAL-0001'}"
```

Expected: `{"status": "ok", "summary": {...}}` with `sentiment` one of the three allowed
values. Then prove the two degraded states, which matter more than the happy path:

```bash
# Stop the model server, run step 3 again -> {"status": "unavailable"}, no traceback.
bench --site dev.localhost set-value "CRM Agent Settings" "CRM Agent Settings" enabled 0
# Run step 3 again -> {"status": "disabled"}, and the client is never called.
```

**The exit gate is the swap.** Repeat step 2's two field changes for each model below and
re-run step 3. Change nothing else — no prompt, no parser, no code. If any model needs a
change above the endpoint, the seam is in the wrong place.

| Model | Note |
|---|---|
| `LiquidAI/LFM2.5-2.6B` | Pythonic tool dialect; confirm guided decoding returns a parsed object |
| `openbmb/MiniCPM5-1B` | Apache 2.0, ~2.2 GB, the cheapest leg |
| `ibm-granite/granite-4.0-h-tiny` | Mamba-2 hybrid MoE, the closest small rehearsal of production |
| `nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4` | W4A16 on Ampere; needs `--tool-call-parser qwen3_coder` |

Record tokens/sec and time-to-first-token for each, measured with the bench running. That
number, not a datasheet, decides whether an always-on loop is viable on this card.

## What is not here yet

MCP transport, write-tier tools, the enrichment fallback extractor, and the assistant
tier. Plans live in `docs/superpowers/plans/`.
