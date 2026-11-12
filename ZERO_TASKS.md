# Zero-score tasks — diagnosis (Phase 0, 2026-11-12)

Source: the template's committed dev-set artifacts
(`~/repos/submission-template/artifacts/`, run `b96-r1`, created
2026-10-20, mean raw reward 0.491 over 29 tasks), read directly:
`manifest.json`, each task's `final_message.md` and `trajectory.json`,
and the captured `solution.py` files for the two MEP tasks.
Nothing here re-derives the scores — every number below is copied from
`manifest.json`.

## Method note and one caveat about which harness produced these runs

`manifest.json` records the same harness tree
(`35113078…`, `my-harness`, `google-cloud/claude-opus-5-5`) for all 29
tasks, but the trajectories fall into two groups:

- The two MEP tasks are from run `run3b`; their trajectories use the Pi
  task-tools names (`exec`, `read_file`, `write_file`) — the same loop
  this repo's `harness.py` + `task-tools.ts` run.
- The other 27 tasks, including `foundation-strategy` and
  `solar-witness-test-package`, are from run `b96-r1`; their trajectories
  use `bash` / `read` / `write` with Anthropic `toolu_` call IDs — a
  direct-API agent loop, not Pi's task-tools relay.

**What this means:** the failure *modes* below are evidence, not
speculation — zero files on disk, a raw-curl auth failure, a
mid-thought final message are all in the artifacts. But for the two
`b96-r1` tasks the failing prompt was that loop's prompt, not the
current `NOTE` in `harness.py`. The harness-level fixes in this phase
therefore target the failure *class* through the levers this harness
actually has (the Pi system-prompt note, the stop-before-deadline
behaviour, and a harness-side final-message fallback), and the write-up
says so per task instead of claiming the exact prompt was the cause.

## 1. `foundation-strategy` — reward 0.0, zero files

### Evidence

- `manifest.json`: `reward: 0.0`, `files: {}`, `ended: "ok"`.
- `final_message.md`, verbatim and complete: `[tool call]`.
- `trajectory.json`: 73 steps. Tool use: `bash` 69, `read` 7, `write` 2.
  The two `write` calls were work files, not deliverables:
  step 58 wrote `work/fdn.py` (calculation engine), step 62 wrote
  `work/opt.py` (design enumeration / optimisation). No write to
  `output/submission.zip` or to any deliverable ever happened.
- Steps 71–73 are all `bash` calls still tuning the optimiser
  (`campus.py` parameter sweeps, then string-replacing constants in
  `opt.py`). Step 73 has **no observation** — the trajectory ends
  mid-tool-call.
- The task instruction itself warned the agent, in its first message:
  "Create a complete submission early, then improve it in place. The
  last file on disk is graded." and "Write a first COMPLETE version of
  `output/submission.zip` within your first ~100 steps, then iterate on
  it in place: the last version on disk when the run ends is what gets
  graded, and a run that exhausts its step or token budget with no file
  scores 0. An imperfect early submission earns partial credit."
  The agent reached only step 73 and still had no file.

### Most likely failure mode (inference, from the evidence above)

The agent spent the whole run optimising (multiprocessing `Pool`
sweeps over design parameters in `opt.py` / `campus.py`) and never
crossed over to writing the deliverable. The run was then cut off —
the missing observation on the final step is consistent with the
6-hour `agent_timeout_sec` expiring mid-command (the artifacts record
no explicit timeout reason, so this is inference, not a recorded
fact) — with nothing on disk, so the task scored 0 despite the
optimisation work presumably being close to done.

### What addresses it (implemented this phase)

- `NOTE` now requires a first COMPLETE version of every deliverable
  within the first ~40% of the time, then improvement in place, and
  states the grading rule explicitly (last file on disk is graded;
  no file = 0; imperfect early beats perfect unfinished).
- `note()` now emits a concrete phase plan with minute marks derived
  from the task's own time limit (explore ~10%, first deliverable
  ~40%, refine to ~75%, verify to ~87.5%, wrap up in the last few
  minutes) — adapted from `plan-verify`'s shares (PLAN 10% / worker
  till 25% remains / verifier till 12.5% remains / fix till 4 min
  remain).
- `NOTE` now requires short exec commands and backgrounding heavy
  compute with polling, because the relay cannot cancel a running
  `exec` (see `task-tools.ts`: an abort only stops the wait; the
  command runs on to its time limit) — a long foreground optimisation
  is exactly what strands a run with no deliverable.
- Harness-side fallback final message (`fallback_message()` in
  `harness.py`): if Pi stops without a final summary, the harness
  lists files modified during the run from the task container instead
  of returning a placeholder. This does not create a missing file —
  nothing can — but it stops the rubric judge from also receiving a
  `[tool call]` fragment when a file *does* exist.

## 2. `solar-witness-test-package` — reward 0.0, zero files

### Evidence

- `manifest.json`: `reward: 0.0`, `files: {}`, `ended: "ok"`.
- `final_message.md`, verbatim and complete: "Now the case tracking
  in OpenProject. Let me check API access." — a mid-thought sentence,
  not a summary.
- `trajectory.json`: 22 steps, tool use: `bash` 23 only — **no MCP
  tool call in the whole run**. Steps 1–21 are document research
  (converting filesystem documents to text, grepping for the six
  municipal arrays and their identifiers).
- Step 22, the last step, runs three raw curls against the OpenProject
  app at `http://127.0.0.1:5009` (`/api/v3/projects`,
  `/api/v3/work_packages`, `/api/v3`). The observation records all
  three answers as
  `{"_type":"Error","errorIdentifier":"urn:openproject-org:api:v3:errors:Unauthenticated","message":"You need to be authenticated to access this resource."}`.
  The trajectory ends there; no further step, no deliverable, no
  recovery attempt.
- The task instruction (step 1 message) required world-app work: "Log
  a scheduling item in the case tracking for each array that is not
  carried, record the batch determination on the case, and close the
  case once the arrays named in the package and the scheduling items
  standing on it agree" and "Return your work as a single Word
  document named `Municipal_Witness_Test_Package.docx`, filed in the
  Program Office's municipal commissioning folder in the document
  store".

### Most likely failure mode (inference)

The agent bypassed the task's MCP servers and went straight at the
world app's raw HTTP API, which needs credentials it did not have —
hence `Unauthenticated` on all three calls. It then stalled: whether
it hit a step/token limit, errored, or simply never produced a next
step is not recorded in the artifacts, so the exact stop cause is
unknown. What is certain is that it never used the provided MCP tools
for the case tracking or the document store, and never fell back to
producing the file deliverable (`Municipal_Witness_Test_Package.docx`)
without the app.

### What addresses it (implemented this phase)

- `NOTE` now has an MCP-first rule: use the task's MCP servers through
  the provided tools for world apps (mail, calendar, documents, CAD,
  project/case tracking); do NOT raw-curl localhost service APIs —
  those calls need credentials the agent does not have and fail
  unauthenticated. If an MCP call fails, look for credentials or
  connection details in the task files, retry the MCP tools, and if the
  app stays unreachable, fall back to producing the file-based
  deliverables rather than stalling on the app.
- Final-message discipline in `NOTE` (summary with exact file paths;
  never a tool call, fragment, or mid-thought sentence) plus the
  `fallback_message()` harness fallback above, for the case where the
  agent still stops mid-thought.
- Note the limit of these fixes: they steer the agent toward the MCP
  tools and toward a file fallback, but if the world app is genuinely
  unreachable *and* the deliverable itself must be filed in the app's
  document store, no prompt can conjure the filing. The file fallback
  at least leaves a gradable document on disk.

## 3. `data-hall-mep-routing` and `data-hall-mep-routing-offset` — reward 0.0 despite a complete-looking `solution.py`

### Evidence

- `manifest.json`: both `reward: 0.0`; each captured exactly one file,
  `output/solution.py` (40,558 and 60,138 bytes; 758 and 1,023 lines).
  No `model.ifc`, no `reconciliation.json` captured.
- The task instruction (step 1 message) defines the deliverable as
  "One self-contained Python script at `output/solution.py` that builds
  the model with ifcopenshell and writes one IFC4 file to `sys.argv[1]`
  (default `output/model.ifc`)". So the grader evidently runs the
  script itself — that is why only `solution.py` is captured, and why
  the agent's own `model.ifc` / `reconciliation.json` on disk at the
  end of the run are not in the artifacts. (Inference from the
  instruction text plus the manifest's file list; the grader itself is
  not available to check against.)
- The agent *did* run its script and its own checks passed. Step 123
  (base task) observation: exit 0, `BYTE-IDENTICAL` across two runs,
  `issues: 0`, `hard clashes 0`, networks connected, `code violations:
  none`, and `ls` shows `model.ifc` (566,469 bytes) and
  `reconciliation.json` written in `output/`. The offset task's
  step 159 shows the same pattern (script run, outputs compared).
- Both final messages are thorough summaries — and both list the same
  set of self-flagged guesses the agent could not resolve from the
  brief: IFC element classes (e.g. CRAH as `IfcUnitaryEquipment` vs
  air handler, PDU as `IfcElectricDistributionBoard`, busway as
  `IfcCableSegment`/BUSBARSEGMENT, tray as
  `IfcCableCarrierSegment`/CABLETRAYSEGMENT), property-set names
  (`Pset_DCM_Rack`, `Pset_DCM_Route` "with alias fields added in case
  the expected names differ"), unit facing (local +Y = front, "the
  most uncertain guess"), same-service segment joints overlapping at
  shared centreline points (23–27 overlaps in the agent's own clash
  report — passes only "if the clash check ignores a service's own
  joints"), and entry-point tolerance (tray/busway starting 360 mm
  from the marked entry in the offset task).
- Both trajectories end cleanly: `notes: "serve stop condition: done"`,
  124 and 160 steps, final messages delivered. No timeout, no
  truncation. These are *content* failures, not process failures.

### Most likely failure mode (inference — the grader is not available)

Score 0 with a complete, self-check-passing script means the failure
is inside what the script produces (or in the grader's run of it):
the most likely candidates, in order, are (a) a schema gate failure
on the guessed element classes / `Pset_DCM_*` names — the agent
itself says the element-type table and property-set names "weren't in
the brief"; (b) the grader counting same-service junction overlaps as
clashes (the agent's own check reports 23–27 of them); (c) a facing /
entry-tolerance mismatch; or (d) the grader's run of `solution.py`
failing in its environment. The artifacts cannot distinguish these —
no grader output is recorded — so no ranking beyond the agent's own
uncertainty ordering is defensible.

### What addresses it (implemented this phase — and its honest limit)

- The verify-before-`done` checklist in `NOTE` now includes: if a
  deliverable is a script the grader runs, run it from a clean output
  directory and check the files it produces. The MEP agent already
  did the equivalent (ran the script, compared byte-identical
  outputs), so this item would **not** have saved these two tasks —
  it is aimed at the silent case where the generator was never re-run.
- No harness-level fix can resolve guessed schema names: the element
  class / property-set table the agent needed was not in the brief it
  could see, and the grader was not available to it. The only
  generally-applicable guidance — already implicit in the agent's own
  behaviour — is to prefer the most standard mapping and to keep the
  script deterministic and re-runnable, which both scripts were.
  **These two zeros are therefore treated as largely unrecoverable by
  harness changes; the expected gain of this phase is concentrated on
  the two zero-file tasks above.**
- Deliberately NOT done: no task-specific IFC knowledge, element-class
  table, or `Pset_DCM_*` list was added to the harness — that would be
  hard-coding task answers, which the fair-play rules forbid, and it
  would only help these two dev tasks, not the 56 hidden test tasks.

## Cross-task pattern

| Task | Files | Steps | Ended | Failure class |
|---|---|---|---|---|
| `foundation-strategy` | 0 | 73 | mid-tool-call, no observation | Process: optimised forever, never wrote a deliverable; cut off with nothing on disk |
| `solar-witness-test-package` | 0 | 22 | after 3× `Unauthenticated` curls | Process: bypassed MCP, raw API auth failure, stalled; no file fallback |
| `data-hall-mep-routing` | 1 (`solution.py`) | 124 | `done` | Content: script complete, self-checks pass, score 0 — likely schema/guess mismatch in the generated model |
| `data-hall-mep-routing-offset` | 1 (`solution.py`) | 160 | `done` | Content: same as above, on the harder hall |

Two of the four zeros are process failures (no deliverable at all) and
are addressable by harness-level prompting and the final-message
fallback. Two are content failures in a script the grader runs, where
the agent's own uncertainty list points at schema guesses no prompt
can verify without the grader.

## What the fixes are worth, arithmetically (illustration, not a prediction)

- Dev-set mean as shipped: 0.4912 (sum 14.246 over 29 tasks).
- Mean of the 25 non-zero tasks: 0.5698.
- If the two zero-*file* tasks had scored at that non-zero mean, the
  dev mean would be 0.5305 (+0.039). If all four zero tasks had, it
  would be 0.5698. These numbers only show the size of the hole the
  zeros leave; they are not a forecast — the fixes have never been run,
  and the MEP pair is judged above to be largely unrecoverable by
  harness changes.
