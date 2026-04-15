"""
LLM Client — unified interface for OpenAI, Anthropic, and DeepSeek APIs.

Tracks token usage per-task for budget enforcement.
"""

import os
import time
import logging
from dataclasses import dataclass, field

import openai
import anthropic

logger = logging.getLogger("agent.llm")


@dataclass
class UsageStats:
    """Accumulated token usage and cost for a run."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_cost_usd: float = 0.0
    api_calls: int = 0

    # Rough pricing per 1M tokens (update as prices change)
    _pricing: dict = field(default_factory=lambda: {
        "gpt-4o":                {"input": 2.50, "output": 10.00},
        "gpt-4.1":               {"input": 2.00, "output": 8.00},
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-opus-4-20250514":  {"input": 15.00, "output": 75.00},
        "deepseek-chat":         {"input": 0.27, "output": 1.10},
        "deepseek-coder":        {"input": 0.27, "output": 1.10},
        "deepseek-reasoner":     {"input": 0.55, "output": 2.19},
    })

    def record(self, model: str, prompt_tok: int, completion_tok: int):
        self.prompt_tokens += prompt_tok
        self.completion_tokens += completion_tok
        self.api_calls += 1
        pricing = self._pricing.get(model, {"input": 5.0, "output": 15.0})
        self.total_cost_usd += (
            prompt_tok * pricing["input"] / 1_000_000
            + completion_tok * pricing["output"] / 1_000_000
        )

    def summary(self) -> str:
        return (
            f"API calls: {self.api_calls} | "
            f"Tokens: {self.prompt_tokens:,} in / {self.completion_tokens:,} out | "
            f"Est. cost: ${self.total_cost_usd:.4f}"
        )


class LLMClient:
    """Unified LLM client supporting OpenAI, Anthropic, and DeepSeek."""

    def __init__(self, config: dict):
        self.config = config
        self.default_provider = config.get("default_provider", "deepseek")
        self.models_config = config.get("models", {})
        self.budget = config.get("budget", {})
        self.usage = UsageStats()

        # Initialize clients lazily based on available keys
        self._openai = None
        self._anthropic = None
        self._deepseek = None

    @property
    def openai_client(self):
        if self._openai is None:
            api_key = os.environ.get("OPENAI_API_KEY")
            if not api_key:
                raise ValueError("OPENAI_API_KEY not set")
            self._openai = openai.OpenAI(api_key=api_key)
        return self._openai

    @property
    def anthropic_client(self):
        if self._anthropic is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")
            self._anthropic = anthropic.Anthropic(api_key=api_key)
        return self._anthropic

    @property
    def deepseek_client(self):
        if self._deepseek is None:
            api_key = os.environ.get("DEEPSEEK_API_KEY")
            if not api_key:
                raise ValueError("DEEPSEEK_API_KEY not set")
            self._deepseek = openai.OpenAI(
                api_key=api_key,
                base_url="https://api.deepseek.com",
            )
        return self._deepseek

    def check_budget(self):
        """Raise if we've exceeded the run budget."""
        max_cost = self.budget.get("max_cost_per_run", 10.0)
        if self.usage.total_cost_usd >= max_cost:
            raise BudgetExceededError(
                f"Run budget exceeded: ${self.usage.total_cost_usd:.4f} >= ${max_cost:.2f}"
            )

    def chat(
        self,
        messages: list[dict],
        system_prompt: str = "",
        provider: str | None = None,
    ) -> str:
        """
        Send a chat completion request.

        Args:
            messages: List of {"role": "user"|"assistant", "content": "..."} dicts.
            system_prompt: System-level instructions.
            provider: Override the default provider for this call.

        Returns:
            The assistant's response text.
        """
        self.check_budget()
        provider = provider or self.default_provider

        if provider == "openai":
            return self._chat_openai(messages, system_prompt)
        elif provider == "anthropic":
            return self._chat_anthropic(messages, system_prompt)
        elif provider == "deepseek":
            return self._chat_deepseek(messages, system_prompt)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _chat_openai(self, messages: list[dict], system_prompt: str) -> str:
        model_cfg = self.models_config.get("openai", {})
        model = model_cfg.get("model", "gpt-4o")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        logger.debug(f"OpenAI request: model={model}, messages={len(full_messages)}")
        start = time.time()

        response = self.openai_client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=model_cfg.get("max_tokens", 4096),
            temperature=model_cfg.get("temperature", 0.2),
        )

        elapsed = time.time() - start
        usage = response.usage
        self.usage.record(model, usage.prompt_tokens, usage.completion_tokens)

        logger.info(
            f"OpenAI response in {elapsed:.1f}s — "
            f"{usage.prompt_tokens} in / {usage.completion_tokens} out"
        )
        return response.choices[0].message.content

    def _chat_anthropic(self, messages: list[dict], system_prompt: str) -> str:
        model_cfg = self.models_config.get("anthropic", {})
        model = model_cfg.get("model", "claude-sonnet-4-20250514")

        logger.debug(f"Anthropic request: model={model}, messages={len(messages)}")
        start = time.time()

        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": model_cfg.get("max_tokens", 4096),
            "temperature": model_cfg.get("temperature", 0.2),
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self.anthropic_client.messages.create(**kwargs)

        elapsed = time.time() - start
        self.usage.record(
            model, response.usage.input_tokens, response.usage.output_tokens
        )

        logger.info(
            f"Anthropic response in {elapsed:.1f}s — "
            f"{response.usage.input_tokens} in / {response.usage.output_tokens} out"
        )
        return response.content[0].text

    def _chat_deepseek(self, messages: list[dict], system_prompt: str) -> str:
        model_cfg = self.models_config.get("deepseek", {})
        model = model_cfg.get("model", "deepseek-chat")

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        logger.debug(f"DeepSeek request: model={model}, messages={len(full_messages)}")
        start = time.time()

        response = self.deepseek_client.chat.completions.create(
            model=model,
            messages=full_messages,
            max_tokens=model_cfg.get("max_tokens", 4096),
            temperature=model_cfg.get("temperature", 0.2),
        )

        elapsed = time.time() - start
        usage = response.usage
        self.usage.record(model, usage.prompt_tokens, usage.completion_tokens)

        logger.info(
            f"DeepSeek response in {elapsed:.1f}s — "
            f"{usage.prompt_tokens} in / {usage.completion_tokens} out"
        )
        return response.choices[0].message.content


class BudgetExceededError(Exception):
    pass
