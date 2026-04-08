# LLM Provider Routing Guide

This document explains how Onyx routes requests to different LLM providers,
with emphasis on the newer providers: OpenAI Codex (OAuth), Claude Code CLI,
Z.AI, and Google AI Studio.

---

## 1. Provider Overview

| Provider | Enum Value | Auth Method | Runtime Path | When to Use |
|---|---|---|---|---|
| **OpenAI** | `openai` | API key | LiteLLM (native) | Standard OpenAI API access with a paid API key |
| **Anthropic** | `anthropic` | API key | LiteLLM (native) | Direct Anthropic API access; full feature support |
| **OpenAI Codex** | `openai_codex` | OAuth (device code flow) | LiteLLM via `openai` custom provider | Use a ChatGPT account (no API key needed); OAuth tokens auto-refresh |
| **Claude Code CLI** | `claude_code_cli` | API key or OAuth/plan login | Subprocess (`claude` CLI binary) | Use Claude via the CLI binary; supports OAuth/plan auth and MCP tools |
| **Z.AI** | `zai` | API key | LiteLLM via `openai` custom provider | Access GLM models through Z.AI's OpenAI-compatible endpoint |
| **Google AI Studio** | `google_ai_studio` | API key | LiteLLM via `gemini` custom provider | Use Gemini models with a Google AI Studio API key (simpler than Vertex) |

---

## 2. Codex Routing: `openai_codex` vs Bundled Codex CLI

### `openai_codex` (OAuth Provider)

- **Auth**: OAuth device code flow against `auth.openai.com`. Users sign in with
  their ChatGPT account; no API key is required.
- **Token management**: Access tokens, refresh tokens, and expiry timestamps are
  stored in `custom_config` under the keys `codex_access_token`,
  `codex_refresh_token`, and `codex_token_expires_at`.
- **Auto-refresh**: At LLM construction time (`LitellmLLM.__init__`), the access
  token is checked for expiry. If expired and a refresh token exists, the token
  is refreshed in-memory via `codex_oauth.refresh_access_token()`.
- **Runtime**: Routes through LiteLLM with `custom_llm_provider="openai"`. The
  OAuth access token is set as the `api_key` on the LiteLLM call.
- **Models**: Standard OpenAI models (`gpt-5.4`, `gpt-5.2`, `o4-mini`, `o3`,
  `o3-mini`, `gpt-4.1`, `gpt-4.1-mini`).
- **Features**: Full LiteLLM feature set -- streaming, tool calling, structured
  output, reasoning, image input.

### When to use which

- **`openai`**: You have an OpenAI API key. Direct billing to your API account.
- **`openai_codex`**: You have a ChatGPT Plus/Team/Enterprise subscription and
  want to use it for API access without a separate API key. OAuth device flow
  handles authentication.

---

## 3. Claude Routing: `anthropic` vs `claude_code_cli`

### `anthropic` (Direct API)

- **Auth**: Standard Anthropic API key.
- **Runtime**: LiteLLM's native Anthropic integration.
- **Features**: Full support for streaming, tool calling, structured output,
  image input, and extended thinking / reasoning effort.

### `claude_code_cli` (Subprocess)

- **Auth**: Either an API key (passed via `--api-key` flag) or OAuth/plan-based
  login (when `auth_mode` is set to `"oauth"`, the API key flag is omitted and
  the CLI uses its own login session).
- **Runtime**: Shells out to the `claude` CLI binary via `subprocess`. This is
  NOT a LiteLLM provider. The `ClaudeCodeCLI` class implements the `LLM`
  interface directly.
- **Invoke mode**: Runs `claude --print --output-format text` for non-streaming
  calls; `claude --print --output-format stream-json` for streaming calls.
- **Limitations** (silently logged as warnings, then ignored):
  - No tool/function calling
  - No structured response format
  - No reasoning effort controls
  - No user identity propagation
  - No token usage reporting (returns zeroed `Usage` objects)
- **Configuration** via `custom_config`:
  - `cli_path`: Path to the `claude` binary (default: `"claude"` on PATH)
  - `auth_mode`: `"api_key"` (default) or `"oauth"`
  - `mcp_config_json`: MCP tool configuration (defined but not yet wired
    into the subprocess invocation)
- **Models**: `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5`

### When to use which

- **`anthropic`**: You have an Anthropic API key and need full-featured access
  (tool calling, structured output, reasoning). This is the recommended choice
  for production workloads.
- **`claude_code_cli`**: You want to use Claude via the CLI binary -- useful
  when you have an Anthropic plan/subscription that authenticates through the
  CLI's own OAuth flow, or when you need MCP tool integration that is only
  available through the CLI. Accept the trade-off of reduced feature support.

---

## 4. Feature Compatibility Matrix

| Feature | `openai` | `anthropic` | `openai_codex` | `claude_code_cli` | `zai` | `google_ai_studio` |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Chat completions | Yes | Yes | Yes | Yes | Yes | Yes |
| Streaming | Yes | Yes | Yes | Yes (stream-json) | Yes | Yes |
| Tool calling | Yes | Yes | Yes | **No** | Yes | Yes |
| Structured output | Yes | Yes | Yes | **No** | Yes | Yes |
| Image input | Yes | Yes | Yes | **No** | Depends on model | Yes |
| Reasoning effort | Yes | Yes (extended thinking) | Yes | **No** | Unknown | Yes |
| MCP tools | No | No | No | Planned (config key defined) | No | No |
| Token usage tracking | Yes | Yes | Yes | **No** (zeroed) | Yes | Yes |
| Cost tracking | Yes | Yes | Yes | **No** | Yes | Yes |

**Notes:**
- `openai_codex` has the same feature set as `openai` because it routes through
  the same LiteLLM `openai` provider; only the auth mechanism differs.
- `zai` routes through LiteLLM's `openai` custom provider, so it inherits
  OpenAI-compatible features. Actual support depends on which GLM model is used.
- `google_ai_studio` routes through LiteLLM's `gemini` custom provider. Gemini
  models support tool calling, structured output, and image input natively.
- `claude_code_cli` explicitly warns and drops unsupported parameters rather
  than raising errors.

---

## 5. Product Decisions

This section captures explicit product-level guidance on when to use each
provider path for overlapping capabilities.

### OpenAI Codex (`openai_codex`) vs Standard OpenAI (`openai`)

Both providers route through LiteLLM to the same OpenAI API. The only
difference is the authentication mechanism.

- **Use `openai_codex` when**: The admin wants to use their ChatGPT
  Pro/Max subscription instead of an API key. This provider supports the
  OAuth device-code flow with automatic token refresh, so there is no
  static API key to manage.
- **Use `openai` when**: The admin has an API key from platform.openai.com.
  Setup is simpler (paste the key), there is no token expiry to worry
  about, and billing goes directly to the OpenAI platform account.

### Claude Code CLI (`claude_code_cli`) vs Anthropic API (`anthropic`)

These two providers have substantially different capabilities and runtime
characteristics.

- **Use `claude_code_cli` when**: The admin needs MCP server access, wants
  to authenticate via an Anthropic plan/subscription (OAuth token instead
  of an API key), or needs Claude's built-in coding tools. Accept the
  trade-off that this is a subprocess-based provider with limited feature
  support (no tool calling, no structured output, no reasoning effort
  controls, no token usage reporting).
- **Use `anthropic` when**: The admin needs full LLM features (tool calling,
  structured output, reasoning / extended thinking), maximum reliability,
  or is running in environments where the `claude` CLI binary is not
  available. This is the recommended choice for production workloads.

### Overlapping Configurations

- It **is valid** to configure both `anthropic` and `claude_code_cli`
  simultaneously. They serve different purposes -- for example, `anthropic`
  for agentic flows that require tool calling, and `claude_code_cli` for
  tasks that benefit from MCP tool access or subscription-based auth.
- It **is valid** to configure both `openai` and `openai_codex`
  simultaneously. One uses an API key, the other uses OAuth. They can
  coexist without conflict.
- Admins **should NOT** configure both providers for the same
  persona/flow. Pick one per use case to avoid ambiguity about which
  provider handles a given request.

---

## 6. Decision Guide

Use this flowchart to choose the right provider:

```
Do you want to use OpenAI models?
  |
  +-- Yes --> Do you have an OpenAI API key?
  |             |
  |             +-- Yes --> Use `openai`
  |             |
  |             +-- No, but I have a ChatGPT Pro/Max subscription
  |                   --> Use `openai_codex` (OAuth device flow, auto token refresh)
  |
  +-- No --> Do you want to use Claude / Anthropic models?
               |
               +-- Yes --> Do you need tool calling, structured output, or reasoning?
               |             |
               |             +-- Yes --> Use `anthropic` (full-featured API)
               |             |
               |             +-- No --> Do you need MCP tools or subscription-based auth?
               |                         |
               |                         +-- Yes --> Use `claude_code_cli`
               |                         +-- No  --> Use `anthropic` (recommended default)
               |
               +-- No --> Do you want to use Gemini models?
                            |
                            +-- Yes --> Do you have a GCP project (Vertex AI)?
                            |            |
                            |            +-- Yes --> Use `vertex_ai`
                            |            +-- No  --> Use `google_ai_studio` (API key)
                            |
                            +-- No --> Do you want to use GLM models (Z.AI)?
                                         |
                                         +-- Yes --> Use `zai`
                                         +-- No  --> Check other providers
                                                     (Bedrock, OpenRouter, etc.)
```

### Quick Reference

| Scenario | Recommended Provider |
|---|---|
| OpenAI models with API key | `openai` |
| OpenAI models with ChatGPT Pro/Max subscription (no API key) | `openai_codex` |
| Claude models -- full features (tool calling, structured output, reasoning) | `anthropic` |
| Claude models -- MCP tools or subscription/OAuth auth | `claude_code_cli` |
| Claude models -- both full features AND MCP tools needed | Configure both `anthropic` and `claude_code_cli` for different flows |
| Gemini models with API key | `google_ai_studio` |
| Gemini models via GCP | `vertex_ai` |
| GLM models (Z.AI) | `zai` |

---

## 7. Runtime Architecture

All providers except `claude_code_cli` flow through the same path:

```
get_llm()  -->  factory.py  -->  LitellmLLM (multi_llm.py)
                                    |
                                    +-- Provider-specific init logic:
                                    |     zai: custom_llm_provider="openai", api_base=Z.AI endpoint
                                    |     google_ai_studio: custom_llm_provider="gemini"
                                    |     openai_codex: custom_llm_provider="openai", api_key=OAuth token
                                    |
                                    +-- litellm.completion() / litellm.acompletion()
```

The `claude_code_cli` provider is intercepted in `factory.py` before reaching
`LitellmLLM`:

```
get_llm()  -->  factory.py  -->  ClaudeCodeCLI (claude_code_cli.py)
                                    |
                                    +-- subprocess.run() or subprocess.Popen()
                                    +-- Parses CLI stdout into ModelResponse / ModelResponseStream
```

### Key files

| File | Role |
|---|---|
| `backend/onyx/llm/constants.py` | `LlmProviderNames` enum, display names, vendor mappings |
| `backend/onyx/llm/factory.py` | `get_llm()` -- dispatches to `ClaudeCodeCLI` or `LitellmLLM` |
| `backend/onyx/llm/multi_llm.py` | `LitellmLLM` -- provider-specific init (ZAI, Codex, Google AI Studio) |
| `backend/onyx/llm/claude_code_cli.py` | `ClaudeCodeCLI` -- subprocess-based LLM implementation |
| `backend/onyx/server/manage/llm/codex_oauth.py` | OAuth device code flow for OpenAI Codex |
| `backend/onyx/llm/well_known_providers/constants.py` | Provider name constants, config keys |
| `backend/onyx/llm/well_known_providers/llm_provider_options.py` | Model lists per provider |
| `backend/onyx/llm/mcp_config_builder.py` | Builds Claude Code CLI MCP config from Onyx DB |
| `backend/onyx/llm/mcp_config_codex.py` | Builds Codex CLI MCP config (TOML) from Onyx DB |

---

## 8. MCP Tool Support

MCP (Model Context Protocol) servers configured in Onyx admin can provide
tools to LLM providers. How those tools reach each provider depends on
the provider's runtime path.

### LiteLLM providers (`openai`, `anthropic`, `zai`, `google_ai_studio`, `openai_codex`)

MCP tools are automatically available through Onyx's tool pipeline. When a
persona has MCP servers attached, Onyx's tool system discovers the servers,
fetches their tool definitions, converts them to the standard function
calling format, and passes them as the `tools` parameter on the LiteLLM
call. No extra provider-level configuration is needed.

### Claude Code CLI (`claude_code_cli`)

MCP servers from Onyx's database are auto-injected via the `--mcp-config`
flag. At invocation time, `ClaudeCodeCLI._build_merged_mcp_config()` calls
`mcp_config_builder.build_mcp_config_for_cli()` to read all CONNECTED
servers from the database and produce a JSON config file. Additional
servers can be added manually via the `mcp_config_json` key in the
provider's `custom_config`.

### Future Codex CLI

If a Codex CLI subprocess provider is added in the future, it would need a
`config.toml` generated from Onyx's MCP database. The utility module
`mcp_config_codex.py` provides `build_codex_mcp_config(db_session)` which
reads CONNECTED servers and produces TOML in Codex's expected format:

```toml
[mcp_servers."server-name"]
url = "https://..."
http_headers = { "Authorization" = "Bearer ..." }
```

This follows the same pattern as the Claude Code CLI builder but outputs
TOML instead of JSON, and only includes HTTP-based transports (SSE,
STREAMABLE_HTTP). STDIO servers are skipped because Codex CLI handles
local command servers differently.
