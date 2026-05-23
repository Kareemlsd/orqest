# Reasoning

`BaseAgent` accepts a `reasoning` keyword that turns on the provider's
thinking or reasoning mode. The value is a single effort level —
`"minimal"`, `"low"`, `"medium"`, or `"high"` — and Orqest translates it
into the right provider-specific `ModelSettings` key at run time.

```python
from orqest.agents import BaseAgent

class Solver(BaseAgent[GlobalState, Answer]):
    ...

agent = Solver(
    agent_name="solver",
    system_prompt="Work step by step.",
    output_type=Answer,
    model="anthropic:claude-sonnet-4-6",
    api_key=...,
    reasoning="medium",
)
```

The four levels are normative across providers. The implementation lives
in `orqest.utils.reasoning`.

## Why one knob instead of provider-specific keys

pydantic-ai exposes thinking through a different `ModelSettings` key for
every provider:

| Provider     | pydantic-ai setting        |
|--------------|----------------------------|
| OpenAI       | `openai_reasoning_effort`  |
| Anthropic    | `anthropic_thinking`       |
| Google       | `google_thinking_config`   |
| OpenRouter   | `openrouter_reasoning`     |

Code that hard-codes one of these keys becomes provider-locked. The
`reasoning` keyword collapses the four into one categorical value and
keeps agent code portable across providers.

## Effort levels

The four levels are ordered from least to most effort. The exact meaning
depends on the provider.

- **`"minimal"`** — the smallest reasoning budget the provider supports.
  On OpenRouter, which does not have a `"minimal"` literal, this collapses
  to `"low"`.
- **`"low"`** — a small reasoning budget; suitable for routine questions
  where the cost of reasoning matters.
- **`"medium"`** — a moderate budget; the recommended default when
  reasoning is enabled.
- **`"high"`** — a large budget; for hard problems where latency and
  token cost are acceptable trade-offs.

For providers that take a numeric token budget rather than a categorical
level (Anthropic and Google), the budgets are:

| Effort     | Thinking-token budget |
|------------|-----------------------|
| `minimal`  | 1024 (Anthropic's documented minimum) |
| `low`      | 4096                  |
| `medium`   | 12288                 |
| `high`     | 24576                 |

## Per-provider translation

The table below shows the `ModelSettings` keys that `reasoning="medium"`
expands into for each provider.

### OpenAI

```python
{
    "openai_reasoning_effort": "medium",
    "openai_reasoning_summary": "auto",   # if not already set
}
```

`openai_reasoning_summary` only takes effect on the Responses API path
(the `openai-responses:` model prefix). Chat completions silently
ignores it. The default of `"auto"` lets OpenAI choose between concise
and detailed summaries per model. Without it, the Responses API runs
reasoning server-side but does not stream summary deltas — pydantic-ai
then emits an empty `ThinkingPart` and downstream UIs (for example
the Vercel AI SDK's `<Reasoning />`) render an empty card.

### Anthropic

```python
{
    "anthropic_thinking": {"type": "enabled", "budget_tokens": 12288},
    "max_tokens": 20480,   # if not already set
}
```

Anthropic requires `max_tokens > budget_tokens` or the request is
rejected. Orqest fills in `max_tokens` (`budget + 8192` headroom) when
the caller has not set it. If the caller passes a `max_tokens` in
`model_settings`, the explicit value is kept.

### Google

```python
{
    "google_thinking_config": {
        "thinking_budget": 12288,
        "include_thoughts": True,
    },
    "max_tokens": 20480,   # if not already set
}
```

`include_thoughts=True` makes Google return the reasoning trace
alongside the answer. The same `max_tokens` rule as Anthropic applies.

### OpenRouter

```python
{
    "openrouter_reasoning": {"effort": "medium", "enabled": True}
}
```

OpenRouter's effort literal has no `"minimal"`, so `reasoning="minimal"`
is translated to `"low"`.

## Precedence

`reasoning` is a convenience layer; explicit keys in `model_settings`
always win.

```python
agent = Solver(
    ...,
    reasoning="high",
    model_settings={"max_tokens": 4096},   # explicit; not overridden
)
```

After resolution, `max_tokens=4096` is kept. The translator never
mutates the caller's settings dict; it returns a new dict that is then
merged into `model_settings`.

## Direct API

The translation function is also available for use outside of
`BaseAgent`.

```python
from orqest.utils.reasoning import resolve_reasoning_settings

extra = resolve_reasoning_settings("anthropic", "medium", base={})
# {"anthropic_thinking": {"type": "enabled", "budget_tokens": 12288},
#  "max_tokens": 20480}
```

The `provider` argument accepts a bare prefix (`"anthropic"`), a model
string (`"anthropic:claude-sonnet-4-6"`), or a pydantic-ai
`Model.system` value (`"google-gla"`). Only the provider segment is
used.

## Supported providers

Reasoning is currently supported for:

- `openai`
- `anthropic`
- `google`
- `openrouter`

Calling with another provider raises `ValueError` with the list of
supported providers. Adding a new provider is a one-line entry in the
`_TRANSLATORS` registry in `orqest/utils/reasoning.py`; no control-flow
edits are needed.

## See also

- [Notebook 05 — Reasoning](https://github.com/Kareemlsd/orqest/blob/main/notebooks/05_reasoning.ipynb)
  exercises the knob across three providers in a single pipeline.
- [`orqest.utils.reasoning`](../api/utils.md) API reference.
