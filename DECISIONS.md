# Decisions — ple-harness-farhan (Phase 0, 2026-11-12)

## D1. `submission.yaml` name stays `my-harness`

**Decision: keep `name: my-harness`. Do NOT rename to `pi-opus` (the kit
sample's name) or to any other name.**

### Why — in plain words

The committed `artifacts/` in this repo are the dev-set run the template
shipped (run `b96-r1`, 2026-10-20, mean raw reward 0.491 over 29 tasks).
Those artifacts are only submittable because they are bound to the exact
harness that produced them:

- `artifacts/manifest.json` records `harness.name: "my-harness"`,
  `harness.model_api: "google-cloud/claude-opus-5-5"`, and `harness.tree` — a
  SHA-256 digest of the harness files as git records them (mode, blob ID,
  path). The evaluation server checks that the submitted harness matches the
  harness that generated `artifacts/` (kit `docs/artifacts.md`, "manifest.json"
  section; template `AGENTS.md` §8).
- `docs/rules.md` (Fair play): "Your committed `artifacts/` must be exported
  by `eval/run.py` from the harness you submit, running the `model_api`
  declared in `submission.yaml`."
- The template's own `README.md` says it outright: "Once you change anything,
  `name` included, step 3 replaces it [the artifacts] with your harness's
  run." Template `AGENTS.md` §8: "Whenever you modify your harness, rerun the
  dev set and commit everything together (`git add -A`): `manifest.json`
  hashes all harness files, and the server checks that your submitted code
  matches the harness that generated `artifacts/`."

Renaming gains nothing for score — `name` is only the leaderboard entry name
(2–39 chars of `a-z0-9-`, starting with a letter or digit; `my-harness`
already satisfies the rule). Renaming would break the binding: the submitted
harness tree/name would no longer match the manifest, the server would flag
"the harness changed after these artifacts were made", and the entry would
need a full fresh dev-set run to regenerate valid artifacts.

We cannot do that re-run on this VM: it has no Docker, no `uv`, no Harbor,
and `eval/run.py` cannot run here. A full Opus dev run also costs roughly
$380–500 at list prices on a machine that can run it. So the only way to keep
a submittable entry right now is to keep the name (and the model, and every
other harness file the manifest hashes) unchanged.

### What would change this decision

- A successful local dev-set re-run (`eval/run.py`) of the renamed harness on
  a machine that can run it (Docker + uv + Harbor + model access), producing
  a fresh `artifacts/` + `manifest.json` bound to the new name/tree — then
  renaming is free and safe.
- farhan explicitly choosing a new entry name **and** accepting the re-run
  cost/time above.

Until either happens, `my-harness` stays.

### Consequence to be aware of

The leaderboard will show this entry as `my-harness`, the same name the
public template uses. That is cosmetic only; it does not affect the score,
and any other team copying the template unchanged would show the same name.

## D2. Sync to the kit's newer `pi-opus` sample — only safe, verifiable changes

The kit's `sample_submissions/pi-opus/` is slightly newer than the template.
We applied only the changes listed in `CHANGES.md`: the `harness.py` Pi
settings (`SETTINGS`, `TIME_NOTE`/`note()`), the kit's `README.md`, and the
kit's `.gitignore`. Everything else was byte-identical already, or was
deliberately not applied (see `CHANGES.md`, "Deliberately NOT applied").

Note the tension this creates, stated honestly: the `harness.py` sync DOES
change the harness tree digest, so strictly by the rules above the committed
`artifacts/` are now bound to the pre-sync harness, not the post-sync one.
`docs/artifacts.md` only carves out documentation changes ("When only
documentation (README, LICENSE, or CHANGELOG) changed after you ran the dev
set, the review prints a note instead of a warning") — a `harness.py` change
is not documentation. The sync is therefore **not free**: it is a deliberate,
documented bet that the kit's newer Pi settings (more retries, longer idle
timeout, streaming cache warming, time-remaining note) are the organizers'
own recommended defaults for this exact harness, and that the entry will be
re-run on the dev set before submission anyway (Phase 1), which regenerates
artifacts bound to the synced harness. If farhan instead wants to submit the
template byte-for-byte with zero re-run risk, the sync can be reverted with
`git revert` — the pre-sync state is the initial commit (`8874c37`).

## D3. No remote, no accounts, no submission from this repo yet

Local-only git repo (`git init`, no remote). Nothing pushed, nothing
submitted, no accounts created. Pushing to GitHub / submitting is a later,
explicit step (needs farhan's repo choice — public vs private + PLE-submission
app — and a dev-set re-run first).

## D4. No second Pi invocation as a verifier — NOTE-level verification instead

**Decision: do NOT add a plan-verify-style second agent run. Verification
lives in the prompt (`NOTE` + `PHASE_NOTE`), inside Pi's single loop.**

The kit's `plan-verify` sample runs three separate conversations
(planner → worker → verifier, plus fix rounds) with per-step time
shares (PLAN 10%, worker till 25% remains, verifier till 12.5%
remains, fix round till 4 min remain). Adapting that literally to this
harness would mean invoking Pi a second time after the first run, with
a fresh conversation containing only the instruction, the plan, and the
worker's summary, and feeding any issues back for a fix round.

Rejected, for three concrete reasons:

1. **Cost/time.** A dev task already runs ~19M cached prompt tokens in
   the single Pi run (see the MEP trajectories' `final_metrics`). A
   verifier pass re-reads the instruction and the deliverables in a new
   context and a fix round re-runs the worker — roughly doubling the
   model cost and the wall-clock time of every task, on a 6-hour
   per-task budget where the template already loses runs to the cutoff.
2. **No safe handoff.** Pi's loop keeps its working state in its own
   conversation; the harness has no record of the worker's plan or
   intermediate reasoning beyond the final message. A verifier run
   would have to reconstruct that from the instruction + final message
   + files on disk, and a second agent with write tools could
   overwrite the worker's deliverables.
3. **Unverifiable here.** A two-invocation orchestration (time
   budgeting across runs, passing state between them, handling the
   second run's own stop-before-deadline) is the kind of change that
   needs a live run to validate, and no run is possible on this VM.

Instead the plan-verify shares are adapted as prompt guidance
(`PHASE_NOTE` minute marks in `note()`) and the verify-before-`done`
checklist is in `NOTE`. This is weaker than a real verifier — the same
agent checks its own work — but it costs nothing extra and cannot
overwrite anything. If a future dev-set run shows verification is
still the binding failure, a second-invocation design can be revisited
with a machine that can run it.

## D5. No vendored `tools/` directory — the agent's libraries come from the task container

**Decision: do not vendor helper scripts or add domain libraries to
`requirements.txt` for the agent.**

Evidence, checked against the template artifacts: the template agents
already used `openpyxl` / `python-docx` (the `.xlsx` / `.docx`
deliverables in scoring tasks) and `ifcopenshell` (the MEP
`solution.py` scripts, 758 and 1,023 lines, run inside the task
container) successfully. Those libraries ship with the task
environment, not with the harness. `requirements.txt` installs into
the *serve* container at build time, so adding libraries there cannot
help the agent inside the task container.

A vendored helper (e.g. a generic deliverable/path checker) was also
considered and rejected: Pi's tools only reach the task container —
`task-tools.ts` routes read/write/bash through the `taskbridge` relay,
and only Pi's own local temp log files are read locally — so there is
no mechanism by which Pi could copy a script from the harness bundle
(`/opt/harness/src`) into the task container. The only channel from
harness to agent is prompt text. The `NOTE` therefore tells Pi to
write its own small verification script inside the task container
when it needs one, rather than the harness pretending to supply one.

## D6. No `cache_control` marks — Pi owns the model requests

**Decision: add no prompt-cache code. The harness never constructs an
Anthropic request, so there is nothing to mark.**

`AGENTS.md` §3 and the `minimal` / `plan-verify` samples put
`"cache_control": {"type": "ephemeral"}` on the system prompt and the
newest message — but those samples build Messages API calls
themselves. In this harness Pi makes the model calls; `harness.py`
only writes `models.json` / `settings.json` / `mcp.json` and spawns
the Pi CLI. The only cache-related knob the harness controls is
`settings.json`, which already sets `"cacheWarming": "streaming"`
(synced from the kit's `pi-opus` sample). Verified by grep: no
`cache_control` string exists anywhere in this repo's code, and no
code path here assembles a request body. If Pi ever exposes a
cache-control setting, that is the place to set it — not this repo.

