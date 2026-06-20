---
sidebar_position: 5
title: Custom Providers
description: How LiteLLM's model-string prefix covers 40+ providers out of the box, how to configure local and proxy endpoints, and when you'd actually need to bypass LiteLLM.
---

# Custom Providers

In pi.dev, adding a new LLM provider means writing a new adapter — hundreds of lines that normalize the provider's streaming format, error codes, and tool call schema to a common internal interface. Pi has 40+ such adapters.

In this project, "adding a provider" is usually just setting an environment variable and changing a model string. LiteLLM handles normalization for all 40+ providers automatically.

This page explains how the model-string prefix system works, how to configure local and proxy endpoints, and the narrow set of cases where you'd actually need to go around LiteLLM.

## How LiteLLM selects a provider

`litellm.acompletion(model=..., ...)` uses the model string to select a provider adapter internally. The routing rules are:

| Model string pattern | Provider |
|---|---|
| `claude-*` (no prefix) | Anthropic |
| `gpt-*`, `o1-*`, `o3-*` (no prefix) | OpenAI |
| `gemini/*` | Google Gemini |
| `vertex_ai/*` | Google Vertex AI |
| `ollama/*` | Local Ollama |
| `openai/*` | Any OpenAI-compatible endpoint (set `api_base`) |
| `bedrock/*` | AWS Bedrock |
| `azure/*` | Azure OpenAI |
| `together_ai/*` | Together AI |
| `groq/*` | Groq |
| `mistral/*` | Mistral AI |
| `cohere/*` | Cohere |

The full list is at [docs.litellm.ai/docs/providers](https://docs.litellm.ai/docs/providers). LiteLLM handles the underlying streaming format, tool call schema translation, and error normalization — your code calls one function and gets OpenAI-compatible chunks back regardless of provider.

## Configuring providers via environment variables

Each provider needs credentials. LiteLLM reads standard environment variable names:

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
OPENAI_API_KEY=sk-...

# Google Gemini
GEMINI_API_KEY=...

# AWS Bedrock
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION_NAME=us-east-1

# Azure OpenAI
AZURE_API_KEY=...
AZURE_API_BASE=https://your-deployment.openai.azure.com
AZURE_API_VERSION=2024-02-01

# Groq
GROQ_API_KEY=...

# Together AI
TOGETHERAI_API_KEY=...
```

Set these in your `.env` file. `python-dotenv` loads them at startup in `main.py`:

```python
from dotenv import load_dotenv
load_dotenv()   # reads .env before any LiteLLM call
```

No code changes in `src/provider.py` — just set the env var and change the model string.

## Local models via Ollama

Ollama runs models locally on your machine. Once it's running (`ollama serve`), point LiteLLM at it with the `ollama/` prefix:

```python
# src/provider.py
MODEL = "ollama/llama3.2"
```

No API key needed. Ollama listens on `http://localhost:11434` by default. LiteLLM knows this.

To use a different Ollama port or a remote Ollama instance:

```python
response = await litellm.acompletion(
    model="ollama/llama3.2",
    messages=full_messages,
    tools=TOOLS_SCHEMA,
    api_base="http://192.168.1.100:11434",   # custom host
    stream=True,
)
```

:::tip
Not all local models support tool calling. Test with a simple non-tool call first. If the model doesn't return structured tool calls, the agent loop will treat every response as a final answer and stop after one turn.
:::

## OpenAI-compatible endpoints (proxies, vLLM, LM Studio)

Any server that speaks the OpenAI REST API can be used via the `openai/` prefix with a custom `api_base`:

```python
# vLLM serving a local model
response = await litellm.acompletion(
    model="openai/my-fine-tuned-model",
    messages=full_messages,
    api_base="http://localhost:8000/v1",
    api_key="not-needed",   # some servers require a non-empty key
    stream=True,
)
```

This works with:
- [vLLM](https://docs.vllm.ai) — high-throughput local inference
- [LM Studio](https://lmstudio.ai) — desktop app with OpenAI-compatible server
- [Jan](https://jan.ai) — similar to LM Studio
- LiteLLM Proxy — a self-hosted gateway that adds rate limiting, logging, and multi-model routing
- Any self-hosted OpenAI-compatible gateway your organization operates

### Using the LiteLLM Proxy

If you're running a LiteLLM Proxy server (useful for teams — it centralizes key management and logs all model calls):

```bash
# Set the proxy base URL and a virtual key
OPENAI_API_BASE=http://your-proxy:4000
OPENAI_API_KEY=sk-virtual-key-from-proxy
```

Then use plain OpenAI model strings — the proxy routes them:

```python
MODEL = "gpt-4o"   # proxy maps this to the real backend
```

## Contrast with pi's hand-written adapters

Pi's `packages/ai/src/providers/` contains one file per provider: `anthropic.ts`, `openai.ts`, `google.ts`, etc. Each adapter:

1. Translates the common message format to the provider's wire format
2. Handles streaming events (SSE, WebSocket, or chunked JSON depending on provider)
3. Normalizes tool call schema differences
4. Maps provider-specific error types to a common error class

This is ~300–500 lines per provider, deeply tested, and required because pi runs in a TypeScript runtime without a LiteLLM equivalent.

In this project, LiteLLM is that abstraction layer. The tradeoff:

| | Pi's adapters | LiteLLM |
|---|---|---|
| Control | Full — you own every line | Partial — depends on LiteLLM releases |
| Maintenance | You maintain each adapter | LiteLLM team maintains providers |
| Feature coverage | Only what you implement | 40+ providers, updated continuously |
| Dependency | None beyond the SDK | `litellm` package (~30 MB) |
| Debugging | Your code, your stack traces | LiteLLM adds an abstraction layer |

For a learning project, LiteLLM wins clearly. For a production system where you need fine-grained control over retry logic, cost tracking, or provider-specific parameters, you might eventually want thinner wrappers.

## When you'd actually bypass LiteLLM

There are real cases where LiteLLM's abstraction gets in the way:

**1. Provider-specific parameters LiteLLM doesn't forward**

Some providers have parameters with no LiteLLM equivalent. LiteLLM may silently drop them. If you need them, call the provider SDK directly for that specific call:

```python
import anthropic

client = anthropic.AsyncAnthropic()

# Direct Anthropic call — bypasses LiteLLM
response = await client.messages.create(
    model="claude-opus-4-5",
    max_tokens=8096,
    # provider-specific param not in LiteLLM
    betas=["some-experimental-feature"],
    messages=messages,
    stream=True,
)
```

**2. A new provider before LiteLLM supports it**

LiteLLM typically adds providers within days of their launch, but if you need to use a brand-new API immediately:

```python
# Minimal custom provider wrapper
import httpx

async def stream_my_provider(messages, system_prompt):
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            "https://api.myprovider.example/v1/chat",
            headers={"Authorization": f"Bearer {os.environ['MY_PROVIDER_KEY']}"},
            json={"messages": messages, "stream": True},
        ) as r:
            async for line in r.aiter_lines():
                # parse provider-specific SSE format
                yield parse_chunk(line)
```

**3. Cost or latency requirements**

LiteLLM adds a small overhead per request (~1–5ms) for format translation. In high-throughput production systems, this can matter. Direct SDK calls skip that layer.

In practice: start with LiteLLM. Bypass it only when you have a concrete requirement it can't meet.

## Related pages

- [Custom Models](./custom-models.md) — changing `MODEL`, per-task model selection
- [Providers and Models](../getting-started/providers-and-models.md) — full provider reference
- [Swapping Providers](../guides/swapping-providers.md) — step-by-step walkthrough
