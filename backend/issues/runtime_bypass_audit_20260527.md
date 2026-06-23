# runtime_bypass_audit_20260527.md

## Scope

This audit only inspected the top of `backend/app/services/chat.py::run_chat_turn`.
No business code or tests were changed.

Relevant product entrypoint:

- `backend/app/services/chat.py:92`

## Summary

`run_chat_turn` has two early-return bypasses before the product runtime opens a DB session and before it persists the user turn through the normal `PipiChatGraph -> PipiLoop` path:

1. `eval_runtime`
2. `smoke_runtime`

Both bypasses return before the normal product path reaches:

```text
persist turn -> InputGate -> PipiChatGraph wrapper -> PipiLoop -> DbPipiAbilityCenter -> Evaluator -> AnswerGate -> persisted response
```

The current code does not expose a response `metadata.runtime_path` marker, so callers and tests cannot reliably distinguish `product` from `eval_bypass` or `smoke_bypass` using the API response alone.

## Bypass Conditions

| Bypass | Location | Trigger condition | Guard setting | Early return |
|---|---:|---|---|---|
| Eval runtime | `backend/app/services/chat.py:96` | `should_use_eval_runtime(payload)` | `PIPI_EVAL_MODE=true` | `return run_eval_chat_turn(payload)` |
| Smoke runtime | `backend/app/services/chat.py:98` | `should_use_smoke_runtime(payload)` | none beyond payload shape | `return run_smoke_chat_turn(payload)` |

## Eval Runtime Bypass

### Trigger

`backend/app/services/eval_runtime.py:469`

```text
PIPI_EVAL_MODE=true
and any of:
- client_context.source == "pipi-eval-lab"
- device_id/device_uid starts with "eval-"
- payload.platform == "eval"
```

### What It Does

`run_eval_chat_turn` creates eval-namespaced DB records and returns deterministic eval results.

Observed path:

- Ensures eval mode at `backend/app/services/eval_runtime.py:224`.
- Creates or updates eval user/conversation namespace.
- Creates a user `Turn`.
- Creates a `Question`.
- Selects seeded answer directly via eval selection logic.
- Creates an `AgentRun` with:
  - `run_type="pipi_eval_chat"`
  - `graph_name="PipiEvalGraph"`
  - deterministic eval model metadata
- Creates eval `RetrievalRun`, `ToolCall`, `RecommendationCard` or `HelpCard`.
- Returns a chat-shaped response.

### Does It Bypass PipiLoop?

Yes.

There is no call to `PipiLoop.run` in `run_eval_chat_turn`. It constructs eval artifacts directly.

### Does It Bypass InputGate?

Yes.

There is no call to `run_input_gate`; intent is implied by eval seed selection and returned metadata.

### Does It Bypass AbilityCenter?

Yes.

It does not use `DbPipiAbilityCenter` or the generic `AbilityCenter`. It directly creates eval tool/card artifacts through eval helper functions. It may still create `ToolCall` rows, but those calls are not produced by the product AbilityCenter boundary.

### Does It Bypass loop_trace?

Yes.

The eval `AgentRun.output_json` contains debug/data/ui-event fields, but not the product harness `loop_trace` with:

```text
input_gate_result
context_pack
reasoner_decision
tool_call
tool_result
evaluator_result
answer_gate_result
```

### Could It Mis-trigger In Real Benchmark Or Production?

Production risk is low if `PIPI_EVAL_MODE=false`, because that setting gates the bypass.

Benchmark risk is high when `PIPI_EVAL_MODE=true`: any normal `/v1/chat/turn` request from `pipi-eval-lab`, any `eval-*` device, or any `platform="eval"` request will bypass the product runtime. That can hide product path failures while making contract/eval calls look green.

Operational risk exists if `PIPI_EVAL_MODE=true` leaks into a shared dev/staging/prod environment.

### Recommendation

Restrict, do not delete.

Recommended next change:

- Add a separate explicit setting such as `ALLOW_EVAL_BYPASS=false` by default.
- Require both `PIPI_EVAL_MODE=true` and explicit caller opt-in, for example `X-Pipi-Eval-Mode: true`, before `/v1/chat/turn` can use eval bypass.
- Add `metadata.runtime_path="eval_bypass"` to eval responses.
- Keep eval reset/seed/trace endpoints behind `PIPI_EVAL_MODE=true`, but do not let ordinary benchmark-shaped payloads silently bypass product runtime.

## Smoke Runtime Bypass

### Trigger

`backend/app/services/smoke_runtime.py:109`

```text
client_context.source == "manual"
and client_context.mode == "remote_smoke"
and client_context.source != "pipi-eval-lab"
and device_id/device_uid does not start with "eval-"
```

No environment setting is required.

### What It Does

`run_smoke_chat_turn` is a fully deterministic in-memory smoke implementation.

Observed path:

- Creates `conversation_id` and `turn_id` in memory.
- Handles publish/chitchat/clarification/recommendation/help-card branches by local matcher.
- Stores cards/help cards in module-level dictionaries `_CARDS` and `_HELP_CARDS`.
- Returns chat-shaped responses with `metadata={}`.

### Does It Bypass PipiLoop?

Yes.

There is no call to `PipiLoop.run`.

### Does It Bypass InputGate?

Mostly yes.

It calls older deterministic helpers such as `detect_chitchat` and `detect_clarification_needed`, but not the product `InputGate` / `run_input_gate` contract used by the harness.

### Does It Bypass AbilityCenter?

Yes.

It creates response data directly and does not use `DbPipiAbilityCenter`, generic `AbilityCenter`, `DbToolExecutor`, or persisted `ToolCall` rows.

### Does It Bypass loop_trace?

Yes.

It does not create `AgentRun` rows and does not return or persist product `loop_trace`. The response metadata is currently `{}`.

### Could It Mis-trigger In Real Benchmark Or Production?

Yes.

The trigger only depends on request payload fields:

```json
{
  "client_context": {
    "source": "manual",
    "mode": "remote_smoke"
  }
}
```

Any client, manual script, or benchmark harness using that shape will bypass the real product runtime even when `PIPI_EVAL_MODE=false`. Existing tests intentionally send `mode="remote_smoke"` in some payloads, so this is the most likely bypass to mask real product failures.

The current guard prevents `pipi-eval-lab` and `eval-*` devices from using smoke, but a non-eval manual benchmark can still trigger it.

### Recommendation

Move to test-only or strictly restrict.

Recommended next change:

- Add `ALLOW_EVAL_BYPASS=false` or a dedicated `ALLOW_SMOKE_BYPASS=false` setting, default false.
- Require explicit header/config opt-in before using smoke bypass.
- Add `metadata.runtime_path="smoke_bypass"` to smoke responses when enabled.
- Prefer moving remote smoke behavior behind a test fixture, separate route, or CLI-only harness instead of keeping it as the first branch in product `/v1/chat/turn`.

## Test Bypass

No explicit `test` bypass branch was found at the top of `run_chat_turn`.

However, the smoke branch effectively acts as a test/manual bypass because it requires only payload shape and no environment guard.

## Cross-cutting Risks

1. **No runtime path marker**

   `product`, `eval_bypass`, and `smoke_bypass` responses are not clearly labeled. Product responses include `metadata.loop`, while smoke metadata is empty and eval metadata is benchmark-oriented, but this is indirect and fragile.

2. **Eval bypass persists DB records but not harness trace**

   Eval runtime creates realistic-looking DB records, including `AgentRun`, `ToolCall`, `RetrievalRun`, and cards. Because these are not produced by `PipiLoop`, they can look valid in admin views while missing harness trace semantics.

3. **Smoke bypass uses in-memory state**

   Smoke cards and help cards are stored in module dictionaries, not durable DB state. This contradicts product runtime expectations and can hide persistence bugs.

4. **Bypasses run before user turn persistence in product path**

   Both bypasses return before the normal product code creates the turn through `run_chat_turn`'s DB session. Eval has its own persistence path; smoke has no product persistence.

## Recommendations By Bypass

| Bypass | Recommendation |
|---|---|
| Eval runtime | Keep but restrict with explicit `ALLOW_EVAL_BYPASS` plus header/config opt-in; mark `metadata.runtime_path="eval_bypass"`; otherwise route `/v1/chat/turn` through product runtime even for benchmark-shaped payloads. |
| Smoke runtime | Move to test-only or require explicit `ALLOW_SMOKE_BYPASS`/`ALLOW_EVAL_BYPASS` plus header/config opt-in; mark `metadata.runtime_path="smoke_bypass"`; do not allow request payload alone to activate it. |
| Product path | Add `metadata.runtime_path="product"` so tests and eval can assert no bypass happened. |

## Verdict

The bypasses are real and both bypass the Hybrid Harness.

Highest priority fix: gate both early returns behind explicit settings/header opt-in and add a `metadata.runtime_path` field. Smoke is riskier than eval because it currently has no environment-level guard.
