# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pi coding agent harness (`@earendil-works/pi-coding-agent`).

Runs one headless Pi session per task. Pi runs in the serve container while the
task's files live in the task container. `task-tools.ts` replaces Pi's built-in
`read`, `write`, `edit`, and `bash` tools with versions that operate on the task
container through `taskbridge.Relay`, and the task's MCP servers are proxied
through the same relay. Pi's agent loop handles model calls, tool execution,
retries, and conversation compaction, returning its last response as the final
message.

The model is configured from the environment variables set by the evaluator in
`models.json` for each task. Claude and Gemini models use their native APIs
under Pi's built-in provider names (`anthropic` and `google`) so Pi's catalog
supplies their limits, thinking support, and image input capabilities. Any other
model uses the OpenAI-compatible `MODEL_BASE_URL` and `MODEL_API_KEY` under a
custom `model` provider with `UNKNOWN_MODEL` limits.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import shlex
import shutil
import subprocess
import tempfile
from typing import Any

import taskbridge

HERE = pathlib.Path(__file__).resolve().parent
# npm ci, from package-lock.json
PI = shutil.which("pi") or str(HERE / "node_modules" / ".bin" / "pi")
# pi's --thinking level: off, minimal, low, medium, high, xhigh or max
THINKING = "max"
# stop pi this long before the deadline (less on short tasks) so its answer
# arrives
STOP_BEFORE_SEC = 90
CATALOG_TIMEOUT_SEC = 30
# Pi settings: retry failed requests up to 8 times with exponential backoff
# from 2 s to 60 s (~4 minutes total, versus Pi's 14 s default), set a 1-hour
# HTTP idle timeout so long max-effort thinking is not cut off at 5 minutes,
# and keep `streaming` cache warming so Pi refreshes Claude's prompt cache
# during long commands.
SETTINGS = {
    "defaultProjectTrust": "never",
    "quietStartup": True,
    "cacheWarming": "streaming",
    "retry": {"maxRetries": 8, "baseDelayMs": 2000, "maxAgentDelayMs": 60000},
    "httpIdleTimeoutMs": 3_600_000,
}
# Request features the Google Cloud route for Claude refuses. pi leaves them
# out, and the Anthropic API works without them too.
COMPAT = {
    "supportsStrictTools": False,
    "supportsMidConvoEffort": False,
    "supportsMidConvoSystemMessages": False,
    "supportsMidConvoToolChanges": False,
}
# A model pi's catalog does not know gets these limits; tune them for yours.
UNKNOWN_MODEL = {"input": ["text"], "contextWindow": 128000, "maxTokens": 16384}
NOTE = (
    "You are working on an engineering task. Your tools act on the task's Linux"
    " container, whose working directory is {workdir}; it has no internet"
    " access. Read the whole instruction and the files it points to, put every"
    " deliverable exactly where and in the format the instruction asks, and"
    " check what you wrote."
    " Work in this order: plan first, then work, then verify — do not start"
    " writing deliverables before you have read the instruction and listed"
    " every deliverable it names, with its exact path and format."
    " Write a first COMPLETE version of every deliverable early, within the"
    " first ~40% of your time, then improve it in place: the last version on"
    " disk is what is graded, and a run that ends with no file scores 0 even"
    " if the work was nearly done. An imperfect early deliverable earns"
    " partial credit; a perfect unfinished one earns nothing."
    " Keep each shell command short (a few minutes at most). Run heavy"
    " compute in the background (nohup ... & with output to a file) and poll"
    " it; never block on one long foreground command — a running command"
    " cannot be cancelled, and a command still running when time expires"
    " leaves nothing on disk."
    " If the task involves a world app (mail, calendar, documents, CAD,"
    " project or case tracking, or any other service listed as an MCP"
    " server), use the MCP tools provided for that server. Do NOT call the"
    " app's HTTP API directly (no curl to localhost service ports): those"
    " calls need credentials you do not have and fail unauthenticated. If"
    " an MCP call fails, look for credentials or connection details in the"
    " task files, try the MCP tools again, and if the app stays unreachable,"
    " fall back to producing the file-based deliverables rather than"
    " stalling on the app."
    " Before you finish, verify: (1) re-run the script or command that"
    " generates each deliverable and confirm it succeeds; (2) list the"
    " deliverables and check every path and filename the instruction names,"
    " exactly; (3) re-read each deliverable and confirm nothing the"
    " instruction asks for is missing; (4) if a deliverable is a script the"
    " grader runs, run it from a clean output directory and check the files"
    " it produces. Only then reply with your summary."
    " Your final reply must be a short summary: what you produced and the"
    " exact path of each file. Never end with a tool call, a fragment, or a"
    " mid-thought sentence — the final message is graded alongside the files."
)
TIME_NOTE = (
    " You have about {minutes} minutes in all; leave time to finish the"
    " deliverables."
)
# Per-phase time plan, adapted from the plan-verify sample's shares (planner
# 10% of total time, worker until 25% remains, verifier until 12.5% remains,
# fix round until 4 minutes remain). Pi runs a single agent loop, so the
# phases are guidance in the prompt, not separate agent invocations; see
# DECISIONS.md D4 for why there is no second Pi run as a verifier.
PHASE_NOTE = (
    " Time plan for this task (~{total} min in all): explore and plan in the"
    " first ~{plan} min; first complete deliverable by ~{draft} min; refine"
    " until ~{refine} min; verify and fix until ~{verify} min; wrap up in"
    " the last few minutes so you finish before the deadline."
)


def note(session: taskbridge.Session) -> str:
  """Returns the text appended to Pi's system prompt for a task.

  Pi is stopped `STOP_BEFORE_SEC` before the deadline, so the prompt note
  reports the remaining time available before that cutoff.

  Args:
    session: Active task session.

  Returns:
    `NOTE` for the task's workdir, plus a time plan when the task has a
    limit long enough for per-phase minute marks (or just `TIME_NOTE`
    for short tasks), and plain `NOTE` when there is no limit.
  """
  left = session.time_left()
  text = NOTE.format(workdir=session.workdir)
  if left is None:
    return text
  total = int(left // 60)
  if total < 30:
    return text + TIME_NOTE.format(minutes=total)
  return text + PHASE_NOTE.format(
      total=total,
      plan=max(1, int(total * 0.10)),
      draft=max(1, int(total * 0.40)),
      refine=max(1, int(total * 0.75)),
      verify=max(1, int(total * 0.875)),
  )


def provider() -> tuple[str, dict[str, Any]]:
  """Returns the Pi provider name and its `models.json` entry.

  Returns:
    A tuple of `(provider_name, provider_config)`.
  """
  if os.environ.get("ANTHROPIC_BASE_URL"):
    return "anthropic", {
        "baseUrl": os.environ["ANTHROPIC_BASE_URL"],
        "api": "anthropic-messages",
        "apiKey": "$ANTHROPIC_API_KEY",
        "compat": COMPAT,
    }
  if os.environ.get("GOOGLE_GEMINI_BASE_URL"):
    return "google", {
        "baseUrl": os.environ["GOOGLE_GEMINI_BASE_URL"] + "/v1beta",
        "api": "google-generative-ai",
        "apiKey": "$GEMINI_API_KEY",
    }
  return "model", {
      "baseUrl": os.environ["MODEL_BASE_URL"],
      "api": "openai-completions",
      "apiKey": "$MODEL_API_KEY",
  }


def in_catalog(name: str, model: str, env: dict[str, str]) -> bool:
  """Checks whether Pi's built-in model catalog recognizes `model`.

  If the probe hangs beyond `CATALOG_TIMEOUT_SEC` or fails, returns `False` so
  the model is configured explicitly with `UNKNOWN_MODEL` limits.

  Args:
    name: Provider name (`anthropic`, `google`, or `model`).
    model: Model identifier string.
    env: Subprocess environment variables for the Pi CLI probe.

  Returns:
    `True` if `(name, model)` appears in `pi --list-models`, else `False`.
  """
  try:
    out = subprocess.run(
        [PI, "--offline", "--list-models", model],
        env=env,
        capture_output=True,
        text=True,
        timeout=CATALOG_TIMEOUT_SEC,
        check=False,
    ).stdout
  except (subprocess.TimeoutExpired, OSError):
    return False
  return any(line.split()[:2] == [name, model] for line in out.splitlines())


def configure(
    agent_dir: pathlib.Path,
    relay: taskbridge.Relay,
    session: taskbridge.Session,
    env: dict[str, str],
) -> tuple[str, str]:
  """Writes Pi's model, settings, and MCP configuration files for a task.

  Args:
    agent_dir: Directory where Pi reads its configuration files.
    relay: Local HTTP relay for the task container and its MCP servers.
    session: Active task session.
    env: Environment dictionary passed to Pi subprocesses.

  Returns:
    A tuple of `(provider_name, model_name)`.
  """
  model = os.environ["MODEL_NAME"]
  name, config = provider()
  models = agent_dir / "models.json"
  # `pi --list-models` reads the provider here
  models.write_text(json.dumps({"providers": {name: config}}))
  if not in_catalog(name, model, env):
    config["models"] = [{"id": model, "name": model, **UNKNOWN_MODEL}]
    models.write_text(json.dumps({"providers": {name: config}}))
  (agent_dir / "settings.json").write_text(json.dumps(SETTINGS))
  servers = {
      s["name"]: {"url": relay.mcp_url(s["name"]), "timeout": 300}
      for s in session.mcp_servers
  }
  (agent_dir / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
  return name, model


class Run:
  """Tracks JSON stream events from a single Pi subprocess run."""

  def __init__(self, session: taskbridge.Session, model: str):
    self.session, self.model, self.replies = session, model, 0

  async def on_event(self, event: dict[str, Any]) -> None:
    """Processes a parsed JSON event from Pi, updating final message and usage.

    Args:
      event: Decoded JSON event dictionary from Pi's stdout stream.
    """
    kind, message = event.get("type"), event.get("message") or {}
    if kind == "message_end" and message.get("role") == "assistant":
      self.replies += 1
      text = "\n".join(
          b.get("text", "")
          for b in message.get("content") or []
          if b.get("type") == "text"
      )
      if text.strip():
        self.session.final_message = text.strip()
      if message.get("stopReason") == "error":
        await self.session.log(
            f"pi: model error: {message.get('errorMessage')}"
        )
      # input_tokens counts cached prompt tokens too
      u = message.get("usage") or {}
      await self.session.usage(
          self.model,
          input_tokens=u.get("input", 0)
          + u.get("cacheRead", 0)
          + u.get("cacheWrite", 0),
          output_tokens=u.get("output", 0),
          cache_read_tokens=u.get("cacheRead", 0),
      )
    elif kind == "tool_execution_start":
      await self.session.log(
          f"pi: {event.get('toolName')} {json.dumps(event.get('args'))[:300]}"
      )
    elif kind in ("auto_retry_start", "compaction_start"):
      await self.session.log(f"pi: {kind} {json.dumps(event)[:300]}")

  async def on_line(self, line: bytes) -> None:
    """Parses a raw stdout line from Pi as JSON and forwards it to `on_event`.

    Args:
      line: Raw line bytes emitted by Pi.
    """
    try:
      event = json.loads(line)
    except ValueError:
      return
    if isinstance(event, dict):
      await self.on_event(event)


async def fallback_message(session: taskbridge.Session) -> str | None:
  """Builds a factual final message from files written during the run.

  Used only when Pi stopped without leaving a final summary (e.g. it was
  cut off mid-tool-call, as happened to one of the template's zero-score
  dev runs, whose final message was literally "[tool call]"). Rubric judges read
  the final message alongside the deliverables, so a list of the files
  actually on disk is worth more than a placeholder. Files modified
  since the task started are the proxy for "written by the agent":
  input files keep their older timestamps and are excluded.

  Returns:
    A short summary listing the files found, or `None` when the listing
    fails, finds nothing, or too little time is left to ask the task
    container. Best effort only; any failure silently yields `None`.
  """
  left = session.time_left()
  if left is not None and left < 30:
    return None
  budget = session.limits.get("agent_timeout_sec")
  minutes = int(budget // 60) + 5 if isinstance(budget, (int, float)) else 360
  try:
    result = await session.exec(
        f"cd {shlex.quote(session.workdir)}"
        f" && find . -type f -mmin -{minutes} | head -40",
        timeout_sec=30,
    )
  except Exception:  # noqa: BLE001 - best effort; a failed listing is not fatal
    return None
  files = [
      line for line in (result.get("output") or "").splitlines() if line.strip()
  ]
  if not files:
    return None
  listed = "\n".join(f"- {path}" for path in files[:40])
  return (
      "The agent stopped without a final summary. Files written during"
      f" this run:\n{listed}"
  )


async def solve(session: taskbridge.Session) -> str:
  """Runs Pi on a single task and returns the final response.

  Creates an isolated temporary agent home, configures tools and MCP servers to
  communicate through `taskbridge.Relay`, and feeds the task instruction on
  standard input.

  Args:
    session: Active task session.

  Returns:
    The final message produced by Pi.

  Raises:
    RuntimeError: If Pi exits before the model produces any assistant reply.
  """
  with tempfile.TemporaryDirectory(
      prefix="pi-",
      dir=os.environ.get("HOME") or None,
      ignore_cleanup_errors=True,
  ) as scratch:
    agent_dir, work = (
        pathlib.Path(scratch) / "agent",
        pathlib.Path(scratch) / "work",
    )
    agent_dir.mkdir()
    work.mkdir()
    async with taskbridge.Relay(session) as relay:
      env = relay.env()
      env.update(
          PI_CODING_AGENT_DIR=str(agent_dir),
          PI_OFFLINE="1",
          PI_SKIP_VERSION_CHECK="1",
          PI_TELEMETRY="0",
          NODE_NO_WARNINGS="1",
          TASK_WORKDIR=session.workdir,
      )
      name, model = await asyncio.to_thread(
          configure, agent_dir, relay, session, env
      )
      argv = [
          PI,
          "--print",
          "--mode",
          "json",
          "--no-session",
          "-nc",
          "-ns",
          "-np",
          "-na",
          "-e",
          str(HERE / "task-tools.ts"),
          "--provider",
          name,
          "--model",
          model,
          "--thinking",
          THINKING,
          "--append-system-prompt",
          note(session),
      ]
      run = Run(session, model)
      done = await taskbridge.run_process(
          argv,
          session,
          env=env,
          cwd=str(work),
          on_line=run.on_line,
          stdin=session.instruction.encode(),
          stop_before_sec=STOP_BEFORE_SEC,
          log_prefix="pi: ",
      )
  if not run.replies:
    raise RuntimeError(
        f"pi exited with {done.code} before the model answered:"
        f" {done.stderr[-2000:]}"
    )
  return (
      session.final_message
      or await fallback_message(session)
      or "(pi stopped without a final message)"
  )
