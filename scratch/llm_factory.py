"""LLM factory — single entry point for every LLM call in the project.

Provider chosen via LLM_PROVIDER env var. Default: ollama (local, free, private).

To swap providers later, set the env var BEFORE running:
    PowerShell:  $env:LLM_PROVIDER = "gemini"
    Bash:        export LLM_PROVIDER=gemini

The rest of the project never imports a provider directly — always goes
through get_llm(). That's what makes "swap Ollama -> Gemini for the final
eval" a one-line change. Imports inside the function are lazy so we don't
load all three SDKs on every call.

Models default to sensible choices per provider; override per-provider with:
    OLLAMA_MODEL   (default: "llama3.2:3b" — fast/small; may flake on strict
                    structured output. Bigger options: "llama3.1:8b", "qwen2.5:7b")
    GEMINI_MODEL   (default: "gemini-3.5-flash")
    OPENAI_MODEL   (default: "gpt-4o-mini")
"""

import os
from langchain_core.language_models import BaseChatModel


def get_llm() -> BaseChatModel:
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        # Low temperature for more deterministic structured-output behavior.
        return ChatOllama(model=model, temperature=0.1)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        # NOTE: Gemini 3.0+ defaults temperature to 1.0. Setting 0.7 here would
        # trigger infinite-loop / degraded-reasoning behavior. Leave it default
        # (1.0) unless you genuinely need bit-stable output, in which case go
        # straight to 0.1 — never the 0.5-0.9 range on Gemini 3+.
        return ChatGoogleGenerativeAI(model=model)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        return ChatOpenAI(model=model, temperature=0.1)

    raise ValueError(
        f"Unknown LLM_PROVIDER={provider!r}. "
        f"Supported: ollama (default), gemini, openai."
    )
