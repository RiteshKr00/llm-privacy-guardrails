"""Day 10 — LLM factory smoke test.

Confirms the chain works end-to-end:
  - LLM_PROVIDER env var (or default) picks a provider
  - get_llm() returns a working ChatModel
  - .invoke() returns a sensible response

If this prints a short string back, the plumbing is good and we're ready
for Day 11 (structured output for the LLM extractor).

Run with the default provider (Ollama):
    python scratch\10_llm_hello.py

Or override via env var (one-shot, doesn't persist):
    $env:LLM_PROVIDER = "gemini"; python scratch\10_llm_hello.py
"""

import os
from llm_factory import get_llm


def main():
    provider = os.getenv("LLM_PROVIDER", "ollama")
    print(f"Provider: {provider}")

    # Show which model is being used so it's clear what got picked
    if provider == "ollama":
        print(f"Model:    {os.getenv('OLLAMA_MODEL', 'llama3.2:3b')}")
    elif provider == "gemini":
        print(f"Model:    {os.getenv('GEMINI_MODEL', 'gemini-3.5-flash')}")
    elif provider == "openai":
        print(f"Model:    {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")

    print()

    llm = get_llm()
    print(f"LLM class: {type(llm).__name__}\n")

    # Two trivial probes to confirm it's actually working.
    prompts = [
        "Say hello in exactly five words. Just the five words, nothing else.",
        "What does the abbreviation PII stand for? One short sentence.",
    ]

    for p in prompts:
        print(f"PROMPT:   {p}")
        response = llm.invoke(p)
        print(f"RESPONSE: {response.content.strip()}\n")


if __name__ == "__main__":
    main()
