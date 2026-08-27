"""Recursive Language Model (RLM) engine and benchmark harness module."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import dspy
from dspy.primitives.code_interpreter import CodeInterpreter
from dspy.primitives.prediction import Prediction
from dspy.primitives.repl_types import REPLHistory, REPLVariable

from agent.interpreter import LocalContainerInterpreter
from agent.tools import ALL_TOOLS


class TaskSolverSignature(dspy.Signature):
    """You are an elite data engineer and autonomous software agent operating inside a Linux container workspace.

Your mission is to solve the given data engineering / programming task accurately, robustly, and efficiently.

## Core Operational Directives:
1. **Recon First & Check All Documentation**:
   - Inspect the workspace (`/app`), read relevant scripts, configurations, schemas, and logs.
   - CRITICAL: Carefully study ALL documents in `docs/` or in the provided context (e.g. `methodology.md`, `data_quality.md`, `codebook.md`, `reporting_conventions.md`). Important business rules, panel exclusions (e.g. pilot/soft launch drops), speeder filters, straight-liner drops, and formula definitions live across these files!
2. **Understand the Discrepancy & Root Cause**:
   - Formulate a clear, verified hypothesis before making changes.
   - For data cleaning / survey tasks, verify which respondents/rows must be filtered out according to data quality and methodology rules before calculating bases or aggregates.
3. **Surgical & Precise Implementation**:
   - Make minimal, targeted code or SQL changes using `patch_file` or `write_file`.
   - Do not guess or apply random edits.
4. **Verification & Clean State Re-runs**:
   - Re-run the task's pipeline or validation script from a clean state.
   - Verify all constraints, row counts, base counts, and edge cases independently.
5. **Completion**:
   - When everything is verified and passes cleanly, call `SUBMIT(summary="...")` with a concise explanation of the root cause, fix applied, and verification confirmation.
"""

    task_instruction: str = dspy.InputField(desc="The task objective and constraints to fulfill.")
    workspace_context: str = dspy.InputField(desc="Initial environment context, directory layout, available skills and documentation.")
    summary: str = dspy.OutputField(desc="A concise summary of the verified solution, root cause, and changes made.")


def get_tools_schema() -> list[dict[str, Any]]:
    """Return OpenAI-compatible tools schema for the trajectory viewer."""
    return [
        {
            "type": "function",
            "function": {
                "name": "python_repl",
                "description": "Execute Python code in the persistent container REPL environment with access to tools (bash, read_file, write_file, patch_file, find_files, grep_search, duckdb_query, llm_query).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "description": "Python code to execute in the container REPL."},
                    },
                    "required": ["code"],
                },
            },
        }
    ]


def record_trajectory(messages: list[dict[str, Any]]) -> None:
    """Persist conversation trajectory to TRAJECTORY_PATH for Harbor viewer."""
    trajectory_path = os.environ.get("TRAJECTORY_PATH")
    if not trajectory_path:
        return

    path = Path(trajectory_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "messages": messages,
        "tools": get_tools_schema(),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class BenchmarkRLM(dspy.RLM):
    """Custom RLM module configured with real-time trajectory recording and terminal feedback."""

    def __init__(
        self,
        max_iters: int = 25,
        max_llm_calls: int = 50,
        sub_lm: dspy.LM | None = None,
    ) -> None:
        super().__init__(
            signature=TaskSolverSignature,
            max_iters=max_iters,
            max_llm_calls=max_llm_calls,
            max_output_chars=12_000,
            verbose=False,
            tools=list(ALL_TOOLS),
            sub_lm=sub_lm,
            interpreter_factory=LocalContainerInterpreter,
        )
        self.trajectory_messages: list[dict[str, Any]] = []

    def _sync_trajectory(self, history_entries: list[Any], final_summary: str | None = None) -> None:
        """Convert REPL history into standardized messages and save trajectory."""
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": TaskSolverSignature.__doc__ or "You are an autonomous data engineering agent.",
            }
        ]

        for idx, entry in enumerate(history_entries):
            reasoning = getattr(entry, "reasoning", "")
            code = getattr(entry, "code", "")
            output = getattr(entry, "output", "")

            thought_block = f"<thought>\n{reasoning}\n</thought>\n\n" if reasoning else ""
            messages.append({
                "role": "assistant",
                "content": f"{thought_block}```python\n{code}\n```",
            })
            messages.append({
                "role": "user",
                "content": f"REPL Execution Output:\n{output}",
            })

        if final_summary:
            messages.append({
                "role": "assistant",
                "content": f"Final Resolution:\n{final_summary}",
            })

        self.trajectory_messages = messages
        record_trajectory(messages)

    def _execute_iteration(
        self,
        repl: CodeInterpreter,
        variables: list[REPLVariable],
        history: REPLHistory,
        iteration: int,
        input_args: dict[str, Any],
        output_field_names: list[str],
    ) -> Prediction | REPLHistory:
        print(f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", flush=True)
        print(f"[RLM Turn {iteration + 1}/{self.max_iters}] Generating action...", flush=True)

        result = super()._execute_iteration(
            repl, variables, history, iteration, input_args, output_field_names
        )

        if isinstance(result, Prediction):
            summary = getattr(result, "summary", "Done.")
            print(f"\n[RLM Turn {iteration + 1}] Completed via SUBMIT!", flush=True)
            print(f"Summary: {summary}", flush=True)
            self._sync_trajectory(history.entries, final_summary=summary)
            return result

        # result is updated REPLHistory
        if result.entries:
            latest = result.entries[-1]
            if latest.reasoning:
                print(f"\nReasoning:\n{latest.reasoning}", flush=True)
            print(f"\nExecuted Code:\n```python\n{latest.code}\n```", flush=True)
            preview = latest.output[:300] + ("..." if len(latest.output) > 300 else "")
            print(f"\nOutput:\n{preview}", flush=True)
            self._sync_trajectory(result.entries)

        return result
