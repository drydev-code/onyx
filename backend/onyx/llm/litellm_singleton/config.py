import json
from pathlib import Path

import litellm

from onyx.utils.logger import setup_logger

logger = setup_logger()


def configure_litellm_settings() -> None:
    # If a user configures a different model and it doesn't support all the same
    # parameters like frequency and presence, just ignore them
    litellm.drop_params = True
    litellm.telemetry = False
    litellm.modify_params = True
    litellm.add_function_to_prompt = False
    litellm.suppress_debug_info = True


# TODO: We might not need to register ollama_chat in addition to ollama but let's just do it for good measure for now.
def register_ollama_models() -> None:
    litellm.register_model(
        model_cost={
            # GPT-OSS models
            "ollama_chat/gpt-oss:120b-cloud": {"supports_function_calling": True},
            "ollama_chat/gpt-oss:120b": {"supports_function_calling": True},
            "ollama_chat/gpt-oss:20b-cloud": {"supports_function_calling": True},
            "ollama_chat/gpt-oss:20b": {"supports_function_calling": True},
            "ollama/gpt-oss:120b-cloud": {"supports_function_calling": True},
            "ollama/gpt-oss:120b": {"supports_function_calling": True},
            "ollama/gpt-oss:20b-cloud": {"supports_function_calling": True},
            "ollama/gpt-oss:20b": {"supports_function_calling": True},
            # DeepSeek models
            "ollama_chat/deepseek-r1:latest": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:1.5b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:7b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:8b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:14b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:32b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:70b": {"supports_function_calling": True},
            "ollama_chat/deepseek-r1:671b": {"supports_function_calling": True},
            "ollama_chat/deepseek-v3.1:latest": {"supports_function_calling": True},
            "ollama_chat/deepseek-v3.1:671b": {"supports_function_calling": True},
            "ollama_chat/deepseek-v3.1:671b-cloud": {"supports_function_calling": True},
            "ollama/deepseek-r1:latest": {"supports_function_calling": True},
            "ollama/deepseek-r1:1.5b": {"supports_function_calling": True},
            "ollama/deepseek-r1:7b": {"supports_function_calling": True},
            "ollama/deepseek-r1:8b": {"supports_function_calling": True},
            "ollama/deepseek-r1:14b": {"supports_function_calling": True},
            "ollama/deepseek-r1:32b": {"supports_function_calling": True},
            "ollama/deepseek-r1:70b": {"supports_function_calling": True},
            "ollama/deepseek-r1:671b": {"supports_function_calling": True},
            "ollama/deepseek-v3.1:latest": {"supports_function_calling": True},
            "ollama/deepseek-v3.1:671b": {"supports_function_calling": True},
            "ollama/deepseek-v3.1:671b-cloud": {"supports_function_calling": True},
            # Gemma3 models
            "ollama_chat/gemma3:latest": {"supports_function_calling": True},
            "ollama_chat/gemma3:270m": {"supports_function_calling": True},
            "ollama_chat/gemma3:1b": {"supports_function_calling": True},
            "ollama_chat/gemma3:4b": {"supports_function_calling": True},
            "ollama_chat/gemma3:12b": {"supports_function_calling": True},
            "ollama_chat/gemma3:27b": {"supports_function_calling": True},
            "ollama/gemma3:latest": {"supports_function_calling": True},
            "ollama/gemma3:270m": {"supports_function_calling": True},
            "ollama/gemma3:1b": {"supports_function_calling": True},
            "ollama/gemma3:4b": {"supports_function_calling": True},
            "ollama/gemma3:12b": {"supports_function_calling": True},
            "ollama/gemma3:27b": {"supports_function_calling": True},
            # Qwen models
            "ollama_chat/qwen3-coder:latest": {"supports_function_calling": True},
            "ollama_chat/qwen3-coder:30b": {"supports_function_calling": True},
            "ollama_chat/qwen3-coder:480b": {"supports_function_calling": True},
            "ollama_chat/qwen3-coder:480b-cloud": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:latest": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:2b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:4b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:8b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:30b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:32b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:235b": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:235b-cloud": {"supports_function_calling": True},
            "ollama_chat/qwen3-vl:235b-instruct-cloud": {
                "supports_function_calling": True
            },
            "ollama/qwen3-coder:latest": {"supports_function_calling": True},
            "ollama/qwen3-coder:30b": {"supports_function_calling": True},
            "ollama/qwen3-coder:480b": {"supports_function_calling": True},
            "ollama/qwen3-coder:480b-cloud": {"supports_function_calling": True},
            "ollama/qwen3-vl:latest": {"supports_function_calling": True},
            "ollama/qwen3-vl:2b": {"supports_function_calling": True},
            "ollama/qwen3-vl:4b": {"supports_function_calling": True},
            "ollama/qwen3-vl:8b": {"supports_function_calling": True},
            "ollama/qwen3-vl:30b": {"supports_function_calling": True},
            "ollama/qwen3-vl:32b": {"supports_function_calling": True},
            "ollama/qwen3-vl:235b": {"supports_function_calling": True},
            "ollama/qwen3-vl:235b-cloud": {"supports_function_calling": True},
            "ollama/qwen3-vl:235b-instruct-cloud": {"supports_function_calling": True},
            # Kimi
            "ollama_chat/kimi-k2:1t": {"supports_function_calling": True},
            "ollama_chat/kimi-k2:1t-cloud": {"supports_function_calling": True},
            "ollama/kimi-k2:1t": {"supports_function_calling": True},
            "ollama/kimi-k2:1t-cloud": {"supports_function_calling": True},
            # GLM
            "ollama_chat/glm-4.6:cloud": {"supports_function_calling": True},
            "ollama_chat/glm-4.6": {"supports_function_calling": True},
            "ollama/glm-4.6": {"supports_function_calling": True},
            "ollama/glm-4.6-cloud": {"supports_function_calling": True},
        }
    )


def load_model_metadata_enrichments() -> None:
    """
    Load model metadata enrichments from JSON file and merge into litellm.model_cost.

    This adds model_vendor, display_name, and model_version fields
    to litellm's model_cost dict. These fields are used by the UI to display
    models grouped by vendor with human-friendly names.

    Once LiteLLM accepts our upstream PR to add these fields natively,
    this function and the JSON file can be removed.
    """
    enrichments_path = Path(__file__).parent.parent / "model_metadata_enrichments.json"

    if not enrichments_path.exists():
        logger.warning(f"Model metadata enrichments file not found: {enrichments_path}")
        return

    try:
        with open(enrichments_path) as f:
            enrichments = json.load(f)

        # Merge enrichments into litellm.model_cost
        for model_key, metadata in enrichments.items():
            if model_key in litellm.model_cost:
                # Update existing entry with our metadata
                litellm.model_cost[model_key].update(metadata)
            else:
                # Model not in litellm.model_cost - add it with just our metadata
                litellm.model_cost[model_key] = metadata

        logger.info(f"Loaded model metadata enrichments for {len(enrichments)} models")

        # Clear the model name parser cache since enrichments are now loaded
        # This ensures any parsing done before enrichments were loaded gets refreshed
        try:
            from onyx.llm.model_name_parser import parse_litellm_model_name

            parse_litellm_model_name.cache_clear()
        except ImportError:
            pass  # Parser not yet imported, no cache to clear
    except Exception as e:
        logger.error(f"Failed to load model metadata enrichments: {e}")


def register_zai_models() -> None:
    """Register Z.AI GLM models with their capabilities in LiteLLM.

    Adds entries to litellm.model_cost directly (register_model may not
    persist) under multiple key formats so lookups always succeed.
    """
    zai_models = {
        "glm-5.1": {
            "max_tokens": 16384,
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": True,
            "litellm_provider": "openai",
        },
        "glm-5-turbo": {
            "max_tokens": 16384,
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "supports_function_calling": True,
            "supports_vision": False,
            "supports_reasoning": False,
            "litellm_provider": "openai",
        },
        "glm-5v-turbo": {
            "max_tokens": 16384,
            "max_input_tokens": 128000,
            "max_output_tokens": 16384,
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": False,
            "litellm_provider": "openai",
        },
    }

    # Register under multiple key formats so litellm lookups always work
    for model_name, info in zai_models.items():
        for prefix in ["", "zai/", "openai/"]:
            litellm.model_cost[f"{prefix}{model_name}"] = info

    # Also use register_model for any version that supports it
    try:
        litellm.register_model(
            model_cost={f"zai/{k}": v for k, v in zai_models.items()}
        )
    except Exception:
        pass  # Direct model_cost insertion is the primary mechanism


def register_claude_code_cli_models() -> None:
    """Register Claude Code CLI models so get_max_input_tokens() works.

    These models are NOT routed through LiteLLM (they use subprocess),
    but registering them here ensures correct token limit lookups.
    """
    cli_models = {
        "claude-opus-4-6": {
            "max_tokens": 32000,
            "max_input_tokens": 200000,
            "max_output_tokens": 32000,
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": True,
            "litellm_provider": "anthropic",
        },
        "claude-sonnet-4-6": {
            "max_tokens": 16384,
            "max_input_tokens": 200000,
            "max_output_tokens": 16384,
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": True,
            "litellm_provider": "anthropic",
        },
        "claude-haiku-4-5": {
            "max_tokens": 8192,
            "max_input_tokens": 200000,
            "max_output_tokens": 8192,
            "supports_function_calling": True,
            "supports_vision": True,
            "supports_reasoning": False,
            "litellm_provider": "anthropic",
        },
    }

    for model_name, info in cli_models.items():
        for prefix in ["", "claude_code_cli/", "anthropic/"]:
            litellm.model_cost[f"{prefix}{model_name}"] = info


def initialize_litellm() -> None:
    configure_litellm_settings()
    register_ollama_models()
    register_zai_models()
    register_claude_code_cli_models()
    load_model_metadata_enrichments()
