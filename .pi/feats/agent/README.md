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
| `install.py` | Idempotent read-only `CRM Agent` role, run from `after_migrate` |

Import direction is one-way: `errors` ← `config`/`schemas`/`context` ← `client` ←
`tools`/`api`. No module imports one to its right.

## Rules

- Reads go through `frappe.get_list`, never `frappe.get_all`, never
  `ignore_permissions`. `tests/test_tools.py` enforces this by parsing the module's
  own AST, so the invariant cannot erode quietly.
- The model is configuration: base URL plus model name. No prompt or parser may be
  model-specific — swapping models must not require a code change.
- Communication bodies are untrusted. They are fenced, the system prompt states that
  fenced text is data rather than instructions, and this layer holds no write tools
  that hostile content could aim at.
- The endpoint degrades: with the flag off or the endpoint down, callers get a status,
  never an exception.

## Running the tests

```bash
cd /workspace/frappe-bench && PYTHONPATH=/workspace bench --site dev.localhost \
  run-tests --app crm --module crm.agent.tests
```

`PYTHONPATH=/workspace` is required in this devcontainer — the bench's `apps/crm` is a
separate checkout, so without it the runner tests that copy rather than the working
tree. No test contacts a model or the network.

## What is not here yet

MCP transport, write-tier tools, the enrichment fallback extractor, and the assistant
tier. Plans live in `docs/superpowers/plans/`.
