# autoskill-local

User-side tooling for [AutoSkill](../../README.md): the `autoskill` CLI and the `autoskill-companion`
MCP server that installed skills call for step-by-step checkpoints and run telemetry.

```bash
pipx install autoskill-local              # or: uv tool install autoskill-local
autoskill login https://autoskill.example # device-code login, registers this machine
autoskill doctor                           # detected agents, companion registration
autoskill trial install my-skill@0.1.0 --target hermes --session <id> --token <token>
autoskill trial sync --watch               # pull corrected builds during a trial
autoskill trial accept <id> --keep         # promote the trial copy (or --remove)
autoskill install --version-id <id> --target openclaw
```

Nothing runs on the AutoSkill server: the agent on this machine executes the skill; the companion only
reports what happens and waits for the person's decisions taken in the AutoSkill web UI.
