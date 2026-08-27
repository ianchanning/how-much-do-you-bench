"""Local Container Interpreter for DSPy RLM.

Provides an in-process, persistent Python 3 REPL executing directly within
the Linux container workspace, giving the LLM full access to tools, the filesystem,
and standard library modules.
"""

from __future__ import annotations

import io
import math
import os
import re
import subprocess
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Callable

from dspy.primitives.code_interpreter import (
    CodeExecutionError,
    CodeInterpreter,
    FinalOutput,
)

from agent.tools import ALL_TOOLS


class _SubmitSignal(Exception):
    """Internal signal raised when code calls SUBMIT()."""

    def __init__(self, output: dict[str, Any]) -> None:
        self.output = output
        super().__init__("SUBMIT called")


class LocalContainerInterpreter:
    """A full-featured Python REPL executing directly in the container environment."""

    execution_instructions: str = (
        "Standard Python 3 execution environment inside the task Linux container. "
        "State and variables persist across iterations. "
        "Standard libraries (os, sys, subprocess, json, re, pathlib, math) and custom helper tools are available. "
        "Always use print() to observe outputs before calling SUBMIT()."
    )

    def __init__(self, tools: dict[str, Callable[..., Any]] | None = None) -> None:
        self._tools: dict[str, Callable[..., Any]] = dict(tools or {})
        self.output_fields: list[dict[str, Any]] = []
        self._globals: dict[str, Any] = {}
        self._started: bool = False

    @property
    def tools(self) -> dict[str, Callable[..., Any]]:
        return self._tools

    def start(self) -> None:
        """Initialize namespace and common utility modules."""
        if self._started:
            return
        self._started = True
        self._globals = {
            "__name__": "__repl__",
            "__doc__": None,
            "__builtins__": __builtins__,
            "os": os,
            "sys": sys,
            "subprocess": subprocess,
            "io": io,
            "re": re,
            "math": math,
            "Path": Path,
        }
        self._globals.update(self._tools)

    def _create_submit_fn(self) -> Callable[..., None]:
        """Create dynamic SUBMIT function matching the expected output fields."""
        output_field_names = [f["name"] for f in self.output_fields]

        def SUBMIT(*args: Any, **kwargs: Any) -> None:
            # Positional argument convenience: SUBMIT("result") when only 1 output field exists
            if args and not kwargs and len(output_field_names) == 1:
                raise _SubmitSignal({output_field_names[0]: args[0]})
            if kwargs:
                raise _SubmitSignal(kwargs)
            # If called empty but 1 field expected, check if 'summary' or similar exists
            if not args and not kwargs and output_field_names:
                raise _SubmitSignal({output_field_names[0]: "Task completed successfully."})
            raise _SubmitSignal({})

        return SUBMIT

    def execute(self, code: str, variables: dict[str, Any] | None = None) -> Any:
        """Execute a block of Python code, capturing stdout, stderr, and SUBMIT signals.

        Args:
            code: Python source code string.
            variables: Variable dictionary to inject into the REPL globals.

        Returns:
            FinalOutput if SUBMIT was called, or string output from stdout/stderr.
        """
        if not self._started:
            self.start()

        # Refresh tools and inject variables
        self._globals.update(self._tools)
        for tool_fn in ALL_TOOLS:
            self._globals[tool_fn.__name__] = tool_fn
        if variables:
            self._globals.update(variables)

        # Inject SUBMIT function
        self._globals["SUBMIT"] = self._create_submit_fn()

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()

        try:
            with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                exec(code, self._globals)
        except _SubmitSignal as sig:
            return FinalOutput(sig.output)
        except SyntaxError as exc:
            raise SyntaxError(f"SyntaxError in code: {exc}") from exc
        except Exception as exc:
            captured_err = stderr_buf.getvalue().strip()
            err_details = f"\nStderr:\n{captured_err}" if captured_err else ""
            raise CodeExecutionError(f"{type(exc).__name__}: {exc}{err_details}") from exc

        stdout_str = stdout_buf.getvalue()
        stderr_str = stderr_buf.getvalue()
        combined = (stdout_str + stderr_str).strip()
        return combined if combined else None

    def shutdown(self) -> None:
        """Clean up REPL globals and reset active state."""
        self._started = False
        self._globals.clear()
