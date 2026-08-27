"""Autonomous Data Engineering Agent powered by DSPy RLM (Recursive Language Model).

Replaces naive chat-completion tool loops with programmatic context exploration,
in-process REPL execution, sub-query decomposition, and rigorous verification.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import dspy

from agent.context import build_workspace_context
from agent.rlm import BenchmarkRLM


def load_environment() -> None:
    """Load .env file if present and variables are unset."""
    for candidate in [Path(".env"), Path("../.env"), Path("/app/.env")]:
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("'\"")
                    if k and k not in os.environ:
                        os.environ[k] = v
            except Exception:
                pass


def configure_dspy(model_name: str) -> dspy.LM:
    """Configure DSPy with the gateway endpoint and model."""
    load_environment()
    gateway_url = os.environ.get("GATEWAY_URL", "https://bench-llm.playground.dataminded.cloud/v1")
    gateway_api_key = os.environ.get("GATEWAY_API_KEY", "unused")

    # Normalize model name for DSPy LiteLLM provider
    clean_model = model_name
    if clean_model.startswith("gateway/"):
        clean_model = clean_model[len("gateway/"):]
    if not clean_model.startswith("openai/"):
        clean_model = f"openai/{clean_model}"

    lm = dspy.LM(
        model=clean_model,
        api_base=gateway_url,
        api_key=gateway_api_key,
        temperature=0.0,
        max_tokens=4096,
    )
    dspy.configure(lm=lm)
    return lm


def main() -> int:
    """Main CLI entrypoint for the agent."""
    parser = argparse.ArgumentParser(description="DSPy RLM Data Engineering Benchmark Agent")
    parser.add_argument("--instruction", required=True, help="Task instruction string")
    parser.add_argument("--model", default=os.environ.get("MODEL", "gemma"), help="Target model name")
    parser.add_argument("--max-turns", type=int, default=30, help="Maximum RLM iterations")
    args = parser.parse_args()

    print(f"=== Initializing RLM Agent ===", flush=True)
    print(f"Model: {args.model}", flush=True)
    print(f"Max turns: {args.max_turns}", flush=True)

    # 1. Configure Language Model
    lm = configure_dspy(args.model)

    # 2. Gather environment and workspace context
    cwd = Path.cwd()
    workspace_context = build_workspace_context(cwd)
    print(f"Discovered workspace context ({len(workspace_context)} characters).", flush=True)

    # 3. Instantiate Benchmark RLM
    rlm = BenchmarkRLM(max_iters=args.max_turns, sub_lm=lm)

    # 4. Execute RLM loop
    try:
        prediction = rlm(
            task_instruction=args.instruction,
            workspace_context=workspace_context,
        )
        summary = getattr(prediction, "summary", "Task completed.")
        print(f"\n==================================================", flush=True)
        print(f"AGENT RUN COMPLETE:\n{summary}", flush=True)
        print(f"==================================================", flush=True)
        return 0
    except Exception as exc:
        print(f"\n[Fatal Agent Error]: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
