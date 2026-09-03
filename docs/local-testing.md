# Local trials

Skills are never executed on the AutoSkill server. A trial is a temporary installation on the
person's own machine, driven by their own agent, observed and steered from the web UI.

```
web UI  --create trial-->  server  <--long-poll--  autoskill-companion (MCP, on the user's machine)
   |                          ^                          ^
   |  decisions               | checkpoints, telemetry   | tool calls
   v                          |                          |
person  <---- explain / preview / verify cards ----  agent (Hermes, OpenClaw, ...)
```

1. `POST /trials` creates the session and a one-time **trial token**; the UI shows the CLI command.
2. `autoskill trial install <skill>@<ver> --target <agent> --session <id> --token <token>` downloads the
   trial package (SKILL.md carries `autoskill_trial`), copies it into the agent's skill folder, registers
   `autoskill-companion` with the token in the agent's MCP config, and reports the install manifest.
3. The agent runs the skill. The SKILL.md companion section makes it call `start_run`, then for each step
   `checkpoint(phase=explain|preview|execute|verify)` and `await_decision` until the person decides.
   The server enforces the order (`explain` -> `preview` -> [`execute`] -> `verify`), never lets a
   simulated (irreversible) step execute, and only mints a confirmation token when the person clicks
   *Authorize real execution* on a preview.
4. *Change* or a coach discussion patches the step instruction, rebuilds the package (`build` + 1) and
   marks the trial stale; `autoskill trial sync --watch` updates the installed copy; the agent receives
   `redo` with `updated_instructions`.
5. The outcome (`accepted`, `changes_requested`, `major_rework`, `removed`) closes the token. The CLI
   then keeps the copy as a permanent install (`trial accept --keep`) or removes it, restoring any
   pre-existing skill folder.

Async mode auto-continues every phase (except real execution of irreversible steps) so agents with
short tool timeouts never block; the person reviews the recorded checkpoints afterwards.
