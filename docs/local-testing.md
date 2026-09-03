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

## Install bundles: one online address for the agent

Every trial, every version you create a download link for, and every public skill on a public hub has an
**install bundle** served under `/dl/...` on the AutoSkill server. Nothing there requires a login: the
token in the URL (or the skill's public visibility) is the authorization, and nothing there can write.

| URL | Content |
|---|---|
| `…/INSTALL.md`, `…/INSTALL.<target>.md` | human-readable installation description (per agent) |
| `…/install.json` | the same, machine-readable (`autoskill-install/1`): every artifact with URL + SHA-256, MCP registration snippets per agent, catalog components, trial callback |
| `…/skill.zip` | the skill folder (trial copies carry `autoskill_trial` in the metadata) with `INSTALL.*.md`, `autoskill.json` (= `install.json`) and the generated MCP sources |
| `…/mcp/<skill>-tools.zip` | the generated MCP server, `pipx install <url>`-able (pyproject at the archive root) |
| `…/components/<slug>/<file>` | the package an administrator uploaded for a catalog component this version depends on |
| `/dl/autoskill-local/latest` | the CLI + companion wheel built by `deploy/install.sh` (or `make local-wheel`) |

Where the addresses come from:

- **Trial**: created with the trial; shown in the launcher dialog and on the trial page (`bundle_url`,
  `manifest_url`). Valid while the trial is open or kept installed. The trial *token* is never inside the
  bundle: the person gives it to the agent (companion env `AUTOSKILL_SESSION_TOKEN`, header
  `X-AutoSkill-Trial` for the `installed` callback).
- **Version**: "Online install links" in the Install tab (`POST /api/v1/versions/{id}/download-links`,
  default 30 days, revocable). The install guide switches to those addresses as soon as a link exists.
- **Public skill on a public hub**: stable `/dl/hub/<project>/<skill>/<version|latest>/...`.

What the agent (or the CLI) does with it:

```bash
autoskill trial install --from <manifest_url> --target hermes --token <trial-token>
autoskill install --from <manifest_url> --target openclaw
```

`--from` downloads `install.json`, verifies every SHA-256, installs catalog components (copied skills,
`pipx`/venv for Python servers), the generated MCP server and the companion, registers all MCP servers in
the agent configuration, asks for the environment values, copies the skill, and reports `installed`.
Removal (`autoskill trial remove`, `autoskill remove`) undoes all of it from the recorded manifest.

Catalog components (admin → Library) can carry an **uploaded package** (zip / wheel / tar.gz, validated
on upload: MCP servers need `pyproject.toml`/`package.json` at the root or a wheel, skills a valid
`SKILL.md` whose name equals the slug) or point to pip / npm / git / a direct URL; either way the bundle
gives the agent a concrete download address and install command, plus the component's own notes.

## Restore, auto-confirm and memory

- **Snapshot / restore.** Before a step changes files or data for real (or on a sandbox copy), the agent
  calls the companion tool `snapshot` with the paths it backs up; copies land in
  `~/.autoskill/sandbox/<run>/<step>/` and the server records what was saved. A real `execute` on a step
  with a restore strategy is refused without a snapshot (`snapshot_required`). On the `execute` or
  `verify` card the person can choose **Restore**: the agent receives the `restore` decision, calls
  `restore_snapshot` (files are put back, non-copyable items are listed for manual restore) and sends a
  `restore` checkpoint; `continue` there starts the next iteration from `explain`.
- **Auto-confirm.** Deterministic steps already confirmed `auto_confirm_after_confirmations` times
  (default 3, admin setting) are decided immediately in later trials (never `execute`, never irreversible
  steps, never after a correction in the same trial). Each trial can switch it off (launcher option or
  "review every step" on the trial page); auto-decided checkpoints are marked in the history.
- **Memory.** After a trial ends with *accepted* or *changes requested*, and after every improvement
  proposal, the `memory.extract` job turns corrections, coach discussions, summaries and analyses into
  skill memory entries (source `trial_discussion` / `improvement`), visible in the Memory tab.

## End-to-end tests (Playwright)

`cd frontend && npm run e2e` starts a real backend (temporary SQLite, inline jobs, console email backend,
`AUTOSKILL_LLM_FAKE=demo`) and the Vite dev server, then drives the browser through registration, project
creation, an interview that completes in one turn with the demo provider, the automatic draft, a trial with
its online install address (fetched without a login), download links, the admin component library with an
uploaded package, and the hub. The demo provider (`autoskill/llm/fake.py::DemoProvider`) answers every
purpose with fixed, well-formed structures, so the same environment is a good way to demo AutoSkill
without a model: `AUTOSKILL_LLM_FAKE=demo make backend-dev`.

In CI the `e2e` job installs Chromium with `npx playwright install --with-deps chromium`; locally the
preinstalled browsers under `PLAYWRIGHT_BROWSERS_PATH` are used. Reports land in `frontend/playwright-report`.
