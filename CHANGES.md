# Changes — pi-opus sync (Phase 0, 2026-11-12)

Source of truth for the sync: kit `~/repos/ple/sample_submissions/pi-opus/`
vs template `~/repos/submission-template/`, compared file-by-file with `diff`.
Base: initial commit `8874c37` (verbatim copy of the template).

## Applied changes

### 1. `harness.py` — Pi settings block (`SETTINGS`)

- **Source:** `sample_submissions/pi-opus/harness.py` (module level, after
  `CATALOG_TIMEOUT_SEC`).
- **Before:** no `SETTINGS` constant; settings were built inline inside
  `configure()`:
  ```python
  settings = {
      "defaultProjectTrust": "never",
      "quietStartup": True,
      "cacheWarming": "off",
      "retry": {"maxRetries": 6, "maxAgentDelayMs": 60000},
  }
  ```
- **After:**
  ```python
  SETTINGS = {
      "defaultProjectTrust": "never",
      "quietStartup": True,
      "cacheWarming": "streaming",
      "retry": {"maxRetries": 8, "baseDelayMs": 2000, "maxAgentDelayMs": 60000},
      "httpIdleTimeoutMs": 3_600_000,
  }
  ```
  and `configure()` now writes `(agent_dir / "settings.json").write_text(json.dumps(SETTINGS))`.
- **Why:** the organizers' newer defaults for this exact harness. More retries
  (6 → 8, with an explicit 2 s base delay, ~4 min total vs Pi's 14 s default)
  survive transient 429/5xx model errors; a 1-hour HTTP idle timeout stops
  long max-effort thinking from being cut off at 5 minutes; `streaming`
  cache warming keeps Claude's prompt cache warm during long commands.
- **Risk: LOW-MEDIUM.** Pure Pi configuration, no protocol or model change.
  Cannot be verified by a live run on this VM (no Docker/uv/Harbor, no model
  access). Note the artifact-binding caveat in `DECISIONS.md` D2: this changes
  the harness tree digest, so a dev-set re-run is required before submission
  for the artifacts to bind to the synced harness.

### 2. `harness.py` — time-remaining note (`TIME_NOTE` + `note()`)

- **Source:** `sample_submissions/pi-opus/harness.py`.
- **Before:** the system prompt passed to Pi was
  `NOTE.format(workdir=session.workdir)` — no mention of remaining time.
- **After:** new constant
  ```python
  TIME_NOTE = (
      " You have about {minutes} minutes in all; leave time to finish the"
      " deliverables."
  )
  ```
  plus a `note(session)` helper that returns `NOTE` plus `TIME_NOTE` with the
  minutes left (from `session.time_left()`, which already exists in the
  template's `taskbridge.py` at line 110), or just `NOTE` when there is no
  limit; `solve()` now passes `note(session)` to `--append-system-prompt`.
- **Why:** Pi previously had no sense of its time budget in the prompt; the
  note tells it how much time is left so it wraps up deliverables instead of
  starting new work late. `note()` degrades gracefully (no limit → plain
  `NOTE`).
- **Risk: LOW.** Prompt text only; `session.time_left()` is already exercised
  by `taskbridge.py` itself (line 1494), so no new API surface.

### 3. `README.md` — replaced with the kit sample's README

- **Source:** `sample_submissions/pi-opus/README.md` (copied verbatim).
- **Before:** the template README ("Submission template: Pi on Claude Opus
  5.5", with "Click Use this template" / "set `name`" instructions).
- **After:** the kit README ("pi-opus: Pi Coding Agent on Claude Opus 5.5"),
  describing how the harness works, how to customize it, and documenting the
  `SETTINGS`/`TIME_NOTE` behaviour.
- **Why:** the template instructions describe how to *use a template*, which
  no longer applies to this repo; the kit README accurately describes the
  harness we now have.
- **Risk: NONE (documentation only).** Per `docs/artifacts.md`, a change to
  README alone gets a note, not a warning, from the artifact review.
- **Known nit:** the synced README links to `../../docs/models.md`, a path
  that resolves inside the kit repo but not in this repo (broken link here).
  Kept byte-identical to the kit sample on purpose so future re-syncs stay a
  clean `diff`; harmless documentation link.

### 4. `.gitignore` — replaced with the kit sample's `.gitignore`

- **Source:** `sample_submissions/pi-opus/.gitignore` (copied verbatim).
- **Before:** comment said "`.env` is committed on purpose (the competition
  reads it from your private repository): never list it here." No `*.env`
  rule.
- **After:** comment "Keys for local runs (`--env-file`) stay out of git and
  out of the build." plus a `*.env` ignore rule. All other entries
  (`.venv/`, `__pycache__/`, `*.pyc`, `runs/`, `node_modules/`) unchanged.
- **Why:** this entry uses `google-cloud/claude-opus-5-5`, which needs no
  `.env` (the evaluator injects the key). Ignoring `*.env` prevents an
  accidental local key file from being committed or built into the bundle.
- **Risk: NONE.** No `.env` file exists in this repo; the rule only affects
  future accidental additions.

## Deliberately NOT applied

| Diff found | Decision | Reason |
|---|---|---|
| `submission.yaml`: `name: pi-opus` (kit) vs `name: my-harness` (template) | **Not applied** | See `DECISIONS.md` D1. Renaming breaks the artifact binding (`manifest.json` records `harness.name: "my-harness"` + tree digest) and gains nothing for score; a rename requires a dev-set re-run we cannot do on this VM. |
| `taskbridge.py` | Nothing to apply — **byte-identical** | `diff -q` clean. (The template's copy already has `Session.time_left()`, which the new `note()` relies on.) |
| `serve.py` | Nothing to apply — **byte-identical** | `diff` clean. |
| `task-tools.ts` | Nothing to apply — **byte-identical** | `diff` clean. |
| `package.json` | Nothing to apply — **byte-identical** | Pi 1.1.0 pinned in both. |
| `package-lock.json` | Nothing to apply — **byte-identical** | Same 70,027-byte lockfile in both. |
| `requirements.txt` | Nothing to apply — **byte-identical** | Same 19-byte file in both. |
| `AGENTS.md`, `LICENSE`, `artifacts/` | Untouched | The kit sample ships neither `AGENTS.md` nor `LICENSE` nor `artifacts/`; the template's copies stay as-is. `artifacts/` is never hand-edited (fair-play rule). |

## Post-sync state

After the sync, `diff -r` of this repo against the kit's `pi-opus/` (excluding
`.git`, `artifacts/`, `AGENTS.md`, `LICENSE`) shows exactly one difference:
`submission.yaml` `name` (`my-harness` here, `pi-opus` there) — the deliberate
decision in `DECISIONS.md` D1.

---

# Changes — zero-task diagnosis + harness fixes (Phase 0, 2026-11-12)

Diagnosis: `ZERO_TASKS.md` (per-task evidence, failure modes, what is
evidence vs inference). All four dev-set zero tasks verified from the
template's committed artifacts (`manifest.json` run `b96-r1` /
`run3b`, mean 0.491 over 29 tasks).

## Applied changes

### 1. `harness.py` — `NOTE` rewritten (early deliverable, MCP-first, time discipline, verify-before-`done`, final-message discipline)

- **Before:** a 4-sentence note (read the instruction, put deliverables
  where asked, check what you wrote, reply with a short summary).
- **After:** the same opening plus five rules:
  - *Plan → work → verify* order, and list every deliverable with its
    exact path/format before writing anything.
  - *First COMPLETE deliverable within the first ~40% of time*, then
    improve in place; states the grading rule (last file on disk is
    graded; no file = 0; imperfect early beats perfect unfinished).
  - *Short exec commands only*; heavy compute in the background
    (`nohup ... &`, poll the output file), never one long foreground
    command — the relay cannot cancel a running `exec`.
  - *MCP-first for world apps:* use the task's MCP servers through the
    provided tools; do NOT raw-curl localhost service APIs (they need
    credentials the agent does not have and fail unauthenticated). If an
    MCP call fails, look for credentials in the task files, retry the
    MCP tools, and if the app stays unreachable, fall back to producing
    the file-based deliverables rather than stalling.
  - *Verify-before-`done` checklist:* re-run each deliverable
    generator; list deliverables and check every path/filename exactly;
    re-read each deliverable; if a deliverable is a script the grader
    runs, run it from a clean output directory and check its outputs.
  - *Final-message discipline:* short summary with the exact path of
    each file; never a tool call, fragment, or mid-thought sentence.
- **Why:** the two zero-*file* tasks failed exactly here.
  `foundation-strategy` (73 steps, 0 files) spent the run optimising
  and was cut off mid-tool-call with no deliverable — despite the task
  instruction itself telling it to write a first complete submission
  early. `solar-witness-test-package` (22 steps, 0 files) did document
  research, then raw-curled OpenProject at `127.0.0.1:5009`, got
  `Unauthenticated` on all three calls, and ended with the mid-thought
  final message "Now the case tracking in OpenProject. Let me check API
  access." Both are process failures the prompt can steer against.
- **Risk: LOW-MEDIUM.** Prompt text only, but it is the harness's main
  lever over the agent: a longer system prompt costs a little context
  on every turn and the new rules are untested — they have never been
  run, on this VM or anywhere (no Docker/uv/Harbor, no model access).
  The 40% early-deliverable rule deliberately trades some solution
  quality for never scoring 0 on a task the agent could partly solve.

### 2. `harness.py` — per-phase time plan in `note()` (`PHASE_NOTE`)

- **Before:** `note()` appended only `TIME_NOTE` ("You have about
  {minutes} minutes in all; leave time to finish the deliverables.").
- **After:** for tasks with ≥ 30 minutes left, `note()` appends
  `PHASE_NOTE` with concrete minute marks computed from the task's own
  limit: explore/plan in the first ~10%, first complete deliverable by
  ~40%, refine until ~75%, verify/fix until ~87.5%, wrap up in the last
  few minutes. For short tasks (< 30 min) it keeps the plain
  `TIME_NOTE`; with no limit it returns plain `NOTE`, as before.
  For a 360-minute dev task the marks are about 36 / 144 / 270 / 315 (computed from time remaining, so in practice a minute under each: 35 / 143 / 269 / 314).
- **Why:** the shares are adapted from the kit's `plan-verify` sample
  (planner 10%, worker till 25% remains, verifier till 12.5% remains,
  fix round till 4 min remain). Pi runs a single agent loop, so the
  phases are prompt guidance, not separate invocations — see
  `DECISIONS.md` D4 for why no second Pi run was added.
- **Risk: LOW.** Pure prompt text computed from `session.time_left()`,
  which already exists. The marks are computed once, at `solve()`
  start, from the full remaining budget; if a task starts late they
  would be based on the remaining time, which is the correct basis.

### 3. `harness.py` — harness-side fallback final message (`fallback_message()`)

- **Before:** `solve()` returned `session.final_message or "(pi
  stopped without a final message)"`.
- **After:** when Pi leaves no final summary, `solve()` runs one short
  `session.exec` (`find . -type f -mmin -<budget+5> | head -40` in the
  task workdir) and returns a factual list of the files written during
  the run. Skipped when < 30 s remain or the listing fails/finds
  nothing; any error yields `None` and the old placeholder is used.
- **Why:** rubric judges read `done.final_message` alongside the
  files. `foundation-strategy`'s final message was literally
  "[tool call]". When a file *does* exist but Pi was cut off
  mid-tool-call, a file list is strictly better than a fragment or a
  placeholder. It cannot create a missing file — nothing can — it only
  improves the message.
- **Risk: LOW.** One extra protocol `exec` (30 s timeout, guarded by
  `time_left()`), best-effort with all failures swallowed. Uses only
  the existing `Session.exec` API from `taskbridge.py`; no new
  protocol surface. The `-mmin` proxy can in principle list a file the
  agent did not write (e.g. a file the task container itself touched
  during the run) — the message says "files written during this run",
  which is the honest description of the proxy.

### 4. `ZERO_TASKS.md` — new diagnosis document

- Per-task write-up of the four zero tasks with file/step evidence,
  most likely failure mode(s), the harness change that addresses each,
  and an explicit evidence-vs-inference split, including the caveat
  that the two `b96-r1` zero-file trajectories use a direct-API loop's
  tool names (`bash`/`read`/`write`), not Pi's task-tools names — so
  the failing prompt there was not this harness's `NOTE`.
- Also records the honest limit: the two MEP zeros are content
  failures (complete script, self-checks pass, score 0 — most likely a
  schema/guess mismatch in the generated model), largely
  unrecoverable by harness changes, and no task-specific IFC knowledge
  was added (fair-play: no hard-coded answers).

## Deliberately NOT done

| Considered | Decision | Reason |
|---|---|---|
| Second Pi invocation as a separate verifier (plan-verify style) | **Not implemented** | See `DECISIONS.md` D4. Doubles model cost/time (a dev task already runs ~19M cached prompt tokens); a fresh verifier context must re-read the instruction + deliverables, and a second agent could overwrite the worker's files. NOTE-level verification (plan → work → verify inside the single loop, with plan-verify's time shares) is the chosen trade-off. |
| Vendored `tools/` helper scripts (e.g. a generic deliverable/path checker) the NOTE tells Pi to copy into the task container | **Not added** | See `DECISIONS.md` D5. (a) The template agents already used openpyxl / python-docx / ifcopenshell successfully *inside* the task container — those ship with the task environment, not the harness. (b) `requirements.txt` installs into the *serve* container, not the task container, so it cannot help the agent. (c) Pi's tools only reach the task container (`task-tools.ts` routes read/write/bash through the relay; only Pi's own local temp log files are read locally), so a script vendored in the repo cannot be copied into the task container by Pi — the only channel is prompt text. The NOTE instead tells Pi to write its own small verification script inside the task container. |
| Claude prompt-cache `cache_control` marks in `harness.py` | **Nothing to add** | See `DECISIONS.md` D6. This harness never constructs an Anthropic request — Pi does. The only cache knob the harness controls is `settings.json`, which already sets `"cacheWarming": "streaming"` (synced from the kit sample). The `cache_control` marks in the `minimal` / `plan-verify` samples apply to harnesses that build Messages API calls themselves; they do not apply to the Pi path. |
| Task-specific IFC element-class / `Pset_DCM_*` knowledge for the MEP tasks | **Not added** | Fair-play: no hard-coded task answers, no fingerprinting of task IDs. It would only help two dev tasks, not the 56 hidden test tasks, and the correct schema names are not in the evidence available to us. |
| Changing `STOP_BEFORE_SEC` (90 s) or `THINKING` | **Not changed** | No evidence in the artifacts that 90 s was the binding constraint (the MEP tasks ended cleanly with `done`; the foundation run was cut off at the task limit, not at the Pi stop). Left at the kit sample's values. |
| `submission.yaml` / model / name | **Untouched** | See `DECISIONS.md` D1. |

## Post-change state

`diff -r` of this repo against the kit's `pi-opus/` (excluding `.git`,
`artifacts/`, `AGENTS.md`, `LICENSE`) now shows, in addition to the
deliberate `submission.yaml` name difference: `harness.py` (NOTE /
`note()` / `fallback_message()`), plus the new repo-only files
`ZERO_TASKS.md`, `CHANGES.md`, `DECISIONS.md`. The artifact-binding
staleness noted in `DECISIONS.md` D2 therefore grows: the committed
`artifacts/` are bound to the pre-sync template harness, and every
further `harness.py` change moves the submitted harness further from
the artifacts. A dev-set re-run before submission (Phase 1) is the
only thing that rebinds them; none of these fixes has been verified by
a run, on this VM or anywhere.

