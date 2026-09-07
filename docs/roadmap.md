# Planned work

Things decided but not built. Each entry says what exists today, so that whoever picks it up starts
from the code rather than from the idea.

## A browser extension that does the installing — **in progress**

> **Built so far**: the native messaging host (`autoskill_local/nativehost.py`) and its eight
> operations — `hello`, `state`, `needs`, `install`, `trial_install`, `trial_settle`, `remove`,
> `assistant` — host registration (`autoskill browser install`), the extension in `extension/`, the
> page side (`frontend/src/lib/localAgent.ts`), the **Do it for me** button on `CopyRow`, and the
> setup package the application hands over. Still ahead: driving the agent (§B of the plan).
>
> One manual step survives and cannot be removed: Chrome has not allowed an extension to be installed
> from a local file since version 33, so the person loads the unpacked folder themselves. The setup
> script does everything up to that point and says so before they start.

Today every act that touches the person's machine is a command they type. `autoskill login`,
`autoskill skill assistant`, `autoskill trial install --from <url> --target hermes --token <token>`,
`autoskill trial accept`, `autoskill install`, `autoskill remove`, `autoskill doctor`
(`packages/autoskill-local/autoskill_local/cli.py`). The web application knows exactly what should
happen — it mints the token, builds the manifest, lists the targets — and then has no way to make it
happen: it prints a line and asks a person to carry it to a terminal.

That gap is where the failures of this product have actually happened. A command shown once and lost.
A token pasted into the wrong window. A skill installed for an agent that was not there. A trial
sitting in `requested` because the terminal step never got done. None of them are hard problems; they
exist only because a human being is the transport between two programs that could talk to each other.

The plan is an extension for Chrome and Opera (both Chromium, one codebase) that performs the local
side directly from the page: install the companion and the `autoskill` assistant skill on first use;
install, refresh and remove skills, MCP servers and scripts; run a trial's install and removal; report
which agents this machine has. The person clicks in the interface they are already looking at.

### The constraint that shapes the whole design

**An extension cannot write to `~/.hermes/skills/` and cannot start a process.** That is not a gap in
the API, it is the sandbox, and no permission unlocks it. Anything that reaches the filesystem does so
through a **native messaging host**: a local executable the browser launches and talks to over stdin
and stdout, registered per browser — a registry key on Windows, a JSON manifest in a per-browser
directory on macOS and Linux.

So the extension does not replace `autoskill-local`; it drives it. That is the good outcome rather
than a compromise: the adapters that know where each agent lives, the checksum verification, the
one-time backup of an agent's MCP config, the null-pruning config writer — all of it stays in one
place, already tested, and gains a second caller. `autoskill-companion` is already an executable
speaking a line protocol over stdio; a `autoskill-native-host` subcommand alongside it is a small
addition, not a new component.

**The bootstrap cannot be eliminated, only reduced to once.** Registering the native host requires
writing outside the browser's reach, so the first installation is still an installer or a command.
What the extension removes is every step after that — which is all of them, and all of the ones that
have gone wrong.

### What has to be built

* `autoskill-native-host` in `packages/autoskill-local`: reads the browser's length-prefixed JSON
  messages, dispatches to the same functions the CLI commands call, writes back progress and result.
  The CLI commands become thin wrappers over those functions if they are not already.
* Host registration in the installers (`install.ps1`, `install.sh`), for Chrome and Opera.
* The extension: a permission-scoped content script on the AutoSkill origin only, a page-facing API
  the frontend calls, and a small state UI (what is installed here, which agents were found).
* An origin allow-list in the host itself. The browser passes the calling extension id, and the host
  must refuse anything that is not the extension we shipped — a native messaging host is a hole
  straight through the sandbox and must be treated as one.
* Frontend: use the extension when present, keep every current command visible when it is not. A
  machine without the extension must lose nothing.

### What it does not change

The token still authorises the trial, the manifest still lists the checksums, the agent still runs
the skill. This removes a transcription step between the application and the machine; it does not
move any decision from the person to the browser. Every install still shows what it will do.

## Upgrading the companion while the agent is holding it

An install now compares the companion version the server advertises with the one on the machine and
upgrades when it is older (`cli.py`, the `kind == "companion"` branch). On Windows that upgrade
**fails whenever the agent is running**, which is nearly always:

```
failed to copy ... \pipx\venvs\autoskill-local\Scripts\python.exe:
The process cannot access the file because it is being used by another process. (os error 32)
```

The agent starts `autoskill-companion.exe`, which runs the `python.exe` inside the pipx virtualenv,
and pipx has to replace that exact file. Nothing is damaged — pipx declines to remove a venv it did
not create, so the existing companion keeps working — but the upgrade never lands, and the person is
told to close their agent, install by hand, and start it again. That is a real instruction rather than
a shrug, and it is currently the only honest one, but it is not an automatic update.

### The shape of the fix

Stop replacing a file that is in use. Install each companion version into its **own** directory —
`~/.autoskill/venvs/autoskill-local-<version>` — and register the agent's MCP command at that path.
Nothing is overwritten, so nothing can be locked; the running agent keeps executing the old copy until
it restarts, which it must do anyway to read the new tool list and instructions. Old versions are
removed later, when no process is using them.

Two things to settle before building it:

* **pipx becomes the odd one out.** `_install_python_package` prefers pipx when present and falls back
  to a private venv; for the companion the fallback would become the rule. Decide whether pipx keeps
  any role here, or whether the companion simply stops using it.
* **The agent must be told the path changed.** Registration writes the command into the agent's own
  MCP config, so an upgrade rewrites that file — which is exactly the file the one-time
  `.autoskill-bak` copy protects. Confirm that path stays correct when it happens on every upgrade
  rather than once.

## Tying every trial and run back to the installed copy

Each trial mints its own session token. The worry is that this scatters the history: several trials
and many runs of the same version, on the same machine, against the same installed skill, with nothing
saying they are the same thing.

### The token was never going to be that link

Worth settling first, because it decides the shape of the fix. `trial_sessions.token_hash` is an
**authentication credential**, not an identity:

* it is scoped to exactly one trial, by construction;
* `reissue_token` replaces it, so it is not even stable within one trial;
* `purge_trial` deletes it with the trial, and the history is supposed to outlive that;
* it is a bearer secret — putting it in a log line or an audit trail is the one thing it must never be.

So no amount of care with tokens produces the correlation. What is needed is a durable identifier for
**this skill installed on this machine for this agent**, minted once and reused by every trial and
every run that touches it.

### What already exists, and what is dead

More is in place than it looks, and one piece of it is inert.

* `runs` carries `skill_id`, `skill_version_id`, `device_id`, `user_id`, `agent_target` and
  `trial_session_id` (`models/trial.py`). Runs of one version on one machine can already be grouped
  today — the four runs on this developer's machine share a version id and a device id.
* `installations` (`models/hub.py`) is exactly the concept wanted: unique on
  `(user_id, device_key, skill_id, target_agent)`, with `kind` distinguishing trial from permanent,
  plus `state`, `run_count` and `last_run_at`.
* **`runs.installation_id` is never written.** The column exists; nothing in the codebase assigns it
  (`services/runs/ingestion.py::start_run` does not take it). Every run ever recorded has it null.
* **A trial never creates an `Installation`.** `record_install` is reached from the download path;
  `confirm_from_run` only *updates* a row that already exists (`if not rows: return None`) and is
  called only on the non-trial branch of `start_run`. On this developer's database, after several
  trials and four runs, `installations` holds zero rows.

So the link is not missing by design — it is designed and unwired.

### What has to be built

* `POST /trials/{id}/installed` records an `Installation` with `kind="trial"`, from the manifest the
  CLI already sends: it knows the device, the target agent, the version and where the files went.
* `start_run` resolves the installation for `(user, device, skill, target)` and sets
  `runs.installation_id`, for trial and production runs alike.
* Backfill for the rows that exist: match on `(user_id, device_id, skill_id, agent_target)` and leave
  null what cannot be matched honestly, rather than guessing.
* Read paths worth having once the column is real: every run of an installed copy across all its
  trials, and the history of a version across the machines that ran it.
* `purge_trial` must not delete the installation — it is shared with the runs that survive, and with
  later trials of the same copy.

### The identity question underneath

`device_key` defaults to `"-"` when no device is known, and a trial's `device_id` is null unless the
person picked a device in the launcher (which defaults to "any device"). Several of the trials on this
machine do carry one, but that is not something to rely on. Before building the above, decide what
identifies a machine when the person never named one — otherwise every unattributed install collapses
into a single shared `"-"` row, which is worse than null: it would assert a link that does not exist.

## Remote MCP servers, called from the local agent

Today a generated MCP server runs as a **stdio subprocess on the machine of the agent**
(`mcp.run(transport="stdio")` in `services/mcpgen/assemble.py`): the client starts it when the
session opens and kills it when it closes. Nothing listens on a port, nothing survives the session.

The plan is to allow the other shape as well: the server **deployed once on a host we control** and
reached over HTTP by the agent running on the person's machine. Note that the direction of the
connection is the comfortable one — the agent calls out, so no public address is needed on the
user's side, unlike the "server pilots the client" idea discussed in
[architecture.md](architecture.md).

### Why it is worth having

* Tools that are heavy to install (pandas, a headless browser) stop having to exist on every machine.
* Credentials for a shared system stay on the server instead of being copied to each user.
* A fix to a tool reaches everyone at once, without reinstalling anything on N machines.
* Agents that cannot run local processes at all can still use the skill.

### The limit to keep in sight

A remote tool **cannot see the person's local files**. The example that started this work — "open
the most recent Excel file in Documents" — is exactly what a remote server cannot do. Remote
delivery suits steps that act on shared or remote data; steps touching the local machine stay local.
Any design that ignores this will produce tools that look right and fail at run time.

### What has to be built

**Central authorisation.** Who may call which tool, decided per project, user and device rather than
per machine. The API keys already carry scopes (`models/api_key.py`) and are the natural starting
point; irreversible tools already require a `confirmation_token` minted by AutoSkill, which is the
per-action half of the same idea.

**Admin review before deployment.** A remote server runs generated code on shared infrastructure, so
a person has to approve it. The version state machine (`services/versioning/`, `services/review/`)
already models draft → built → trial passed → approved → published: deployment becomes another state
in that chain, not a separate mechanism.

**Automated danger review.** Today `services/mcpgen/spec.py` runs `check_python_source` with an
allowlist of imports and a closed list of pip packages. That is a syntactic check. Running code on
shared infrastructure asks for a judgement about *behaviour*: network calls to arbitrary hosts,
writes outside the sandbox, subprocesses, reads of credentials or of files belonging to other
tenants. The output should be a risk level attached to the version, feeding the human review rather
than replacing it.

**Reuse before generation.** Before writing a new server, look for an existing one that already
exposes the same capability — matched on the tool schemas, not on names, since two skills will
describe "send an email" differently. The library catalog already suggests shared components to the
interview (`services/library/catalog.py`, and the intake prompt tells the model to prefer them), so
the discovery half exists; what is missing is the comparison and the decision. Where a server is
close but not identical, **extending it** with a new tool is usually better than cloning it, and
needs its own versioning story.

**Lifecycle.** The questions to answer explicitly, because the wrong default here is expensive:

* A new version of the skill is published — is a second server deployed alongside, or is the running
  one updated in place? Both, presumably, depending on whether the tool signatures changed.
* Two versions live at once while installations migrate. `installations` records which version each
  machine has, so the server can know when the old one has no users left.
* The skill is deleted or suspended. A remote server outliving its skill is an orphan with
  credentials: retirement needs an owner, a grace period, and a rule for what happens to runs still
  in flight.
* Nobody has called a server for months. Undeploying is cheap; undeploying something still used by
  one forgotten cron job is not.

### Where it would live

`services/mcpgen/` produces the package; a new `services/mcpdeploy/` would own the deployment,
its state and its lifecycle, leaving the generator unaware of where its output ends up. The
`McpServer.runtime` column already distinguishes what was written (`python-mcp`, `python-cli`), and
is the place to record a remote deployment as a third shape.

## Somewhere better than a folder to keep the files

Today every byte a skill is made of lives in one directory on the server:
`data/store/objects/<first two characters>/<sha256>`, written by
`services/storage/content_store.py`. The database keeps the structure — `SkillVersion.manifest` and
`McpServerVersion.manifest` are `{"files": [{path, hash, size}]}` — and the store keeps the content,
addressed by hash, so an identical file stored twice costs one copy and a published version can
never lose its bytes.

That much is sound. Two things are not.

**Nothing is ever deleted.** `ContentStore.delete()` exists and *nobody calls it*; `Blob.ref_count`
is declared in `models/blob.py` and *no code reads or writes it*. Delete a skill and its rows
cascade away while its blobs stay behind, unreferenced and unfindable. The store only grows, and
there is no way to ask what is in it, what still matters, or what an old version is costing.

**It only works on one machine.** A local directory rules out more than one API process, rules out
object storage, and makes backup a matter of remembering to copy `data/store/` alongside the
database — in that order, or the copy is inconsistent.

What to build:

* A **storage backend behind the `ContentStore` interface** — S3-compatible object storage, or a
  volume the server does not own — chosen by configuration. The interface is already narrow
  (`put`, `get`, `exists`, `delete`), which is what makes this replaceable rather than rewritten.
* **Reference counting that is actually kept**, so the question "is this blob still needed" has an
  answer. `Blob.ref_count` is the field; what is missing is a writer for it, at every point that a
  manifest is created or dropped.
* **A way to look**: how much a project, a skill or a version occupies, which blobs no manifest
  mentions any more, when each was last read.
* **A retention policy that a person decides**, not a cron that guesses: old builds of a version,
  drafts never published, attachments of abandoned interviews. Deletion must never be able to reach
  a published version — that is the one guarantee the current design gets right by accident, and it
  should become deliberate.

### MinIO as the concrete choice

The obvious backend is **MinIO**: S3-compatible, self-hosted, and therefore keeping the property
this project cares about most — a server anyone can install on their own machines, with nothing
required from a cloud account. The same code then also works against real S3 or any compatible
service, because the API is the same; MinIO is the default, not a lock-in.

**What it stores.** Exactly what the store holds today: the documents people attach to an interview,
the `SKILL.md` and its files, and the **generated scripts as source** — the tool modules and the CLI
are plain `.py` text, not build output. That matters for what to expect of the backend: these are
small, immutable, text-shaped objects, written once and read many times, never edited in place.

**Where the work is.** Five files call `get_content_store()`
(`interview/attachments.py`, `library/artifacts.py`, `mcpgen/generator.py`, `packaging/store.py`),
and all of them use four methods. A `MinioContentStore` implementing `put`/`get`/`exists`/`delete`
with the key `<first two characters>/<sha256>` — the same layout, so an existing directory can be
mirrored across with `mc mirror` and nothing else changes — is a small class plus a settings switch.
`boto3` is not a dependency today and would be the one addition.

**What it settles, beyond the folder.** Several API processes can share one store, backup becomes
`mc mirror` on a schedule instead of a directory copy that must be ordered against the database
dump, and **lifecycle rules do part of the rubbish problem natively**: a bucket can be told to move
objects nobody has read for a year to cheaper storage, or to expire them, without any code of ours.
Reference counting is still needed to know *which* objects are safe to expire — that judgement is
ours, not the storage's — but the mechanics of tiering and expiry are not something to write.

**What not to expect from it.** Object versioning on the bucket is redundant here: content is
addressed by hash, so a changed file is a different object and nothing is ever overwritten. Turning
it on would only keep copies of deletions. And a GET over the network is slower than a local read,
which matters for the small files read on every request — a bounded local cache in front of the
store is the answer, and it stays correct precisely because objects are immutable.

**Keep the folder.** For a single machine — the way this runs today — MinIO is one more service to
operate and one more secret to hold. The local directory should remain the default and MinIO the
choice you make when there is more than one process, or when the data outgrows the disk.

## Handing work over to somebody else

Someone falls ill, goes on holiday, changes team — and the skills they built, the interviews they
left half-finished and the runs their machine was carrying should not go with them.

What exists to build on: `Project` has members with roles (`owner`, `editor`, `viewer`);
`Skill.created_by` and `Project.created_by` record who made them (both `ON DELETE SET NULL`, so a
departure does not destroy the work); `Installation` records who installed which version on which
device; interviews and trials carry a `user_id`.

What is missing is that none of this is *transferable*, and one part of it cannot be transferred at
all:

* **Ownership of a skill and of the work in flight** — an interview stopped at turn twelve, a trial
  waiting on a checkpoint. Handing these over means changing who answers, who is notified, and who
  is allowed to confirm — and saying so in the transcript, so the record shows a second person took
  over rather than the first one changing their mind.
* **The installations.** They are per user *and* per device (`uq_installation`), which is right: the
  skill is on a machine that belongs to somebody. A handover cannot move an installation, it can
  only ask the new person to install it on theirs — and tell them exactly what to install.
* **The credentials, which today cannot be handed over at all.** Environment values are entered on
  the person's own machine and stored only in their agent configuration (`cli.py::_ask_env`, "stored
  only in your agent configuration"); the server never sees them. So a handover transfers *what the
  skill needs* — the names of the values, from the version's `env_requirements` — never the values
  themselves, and the successor supplies their own. For a personal password that is the only sane
  arrangement and it should stay so: a colleague's holiday must not hand over their mailbox. For a
  service account belonging to the team it is not a principle at all, only a consequence of where the
  values happen to live. **A vault for the keys, passwords and environment values**, below, is what
  turns that difference into something the system can enforce rather than assume.

The interesting part is therefore not the database update but the **checklist**: what the successor
must install, which values they must provide under their own name, which sessions are now theirs,
and what the previous person had already decided so that it is not asked again.

### When a manager does the transfer

Everything above describes two people, one of whom is present. The case that actually arrives is the
other one: somebody has left, or is ill, or is simply unreachable, and their work has to move without
them. That is a different operation, not a gentler version of the same one.

What it needs that a consensual handover does not:

* **An authority that exists.** The strongest role today is `owner` on a project, and it does not
  include reassigning what another person created. Either project ownership grows that power
  explicitly — the cheapest answer, and coherent with the project being the unit a team shares — or
  it waits for the organisation model that *Seeing across people* below also turns out to need. What
  it must not be is something an administrator does directly in the database: either it is a named
  power, visible in the interface and recorded when used, or it is an incident.
* **A record of who moved it, and why.** A handover can honestly be written as the first person's own
  decision. This one cannot. The transcript has to show that a third party moved the work, when, and
  on what grounds — otherwise an interview that changed hands at turn twelve reads for ever after as
  one person inexplicably changing their mind.
* **A scope larger than one skill.** A departure is never one skill: it is everything that person
  owns inside a project — skills, drafts, interviews stopped mid-question, trials waiting on a
  checkpoint. So the operation is *move what X owns in project P to Y*, and it shows exactly what
  would move before moving it. A list of twenty items is precisely the moment somebody notices that
  four of them should be retired rather than inherited.
* **Reassigning and revoking are two operations, not one.** A holiday adds a second owner and takes
  nothing away. A departure adds the successor *and* removes the predecessor. Merging them into a
  single "transfer" button is how somebody comes back from two weeks off unable to open their own
  work.
* **And the line the vault draws.** A manager can move the skill, its versions and the sessions in
  flight, and can grant the successor the organisation's own credentials. A manager cannot move, and
  cannot read, a personal one: the successor inherits the *names* and supplies their own values. That
  single sentence is what keeps "a manager may reassign work" from quietly meaning "a manager may
  read a colleague's mailbox".

## A vault for the keys, passwords and environment values

Every skill that touches anything real needs values it must not carry in its own text: an API key, a
database password, a token, an account name. Today **the names travel and the values do not**, and
much of the entry above turns on that single fact.

**The names already flow end to end**, which is the good news and makes this an addition rather than a
redesign. The interview collects them — `Integration.credentials_needed` and
`Constraints.secrets_needed`, both commented *names only*, with gate G9 refusing a document whose
integrations declare neither credentials nor authorizations. The build records them per version:
`SkillVersion.env_requirements` and `McpServerVersion.env_requirements`, each entry shaped
`{name, description, secret}`. The installer then asks for every one of them on the machine
(`cli.py::_ask_env`) and writes what it is told into the agent's own configuration.

That pipeline ends in a value typed into a config file on one laptop, and everything wrong with the
present situation follows from that ending: the same secret is retyped on every machine and nobody
can say where it now lives; rotating it means remembering which machines have it; a handover cannot
carry it; central execution cannot happen at all; and the value's final resting place is a plain
configuration file, which is the location least able to protect it.

### What `core/crypto.py` is, and what it is not

There is already encryption in the codebase, and it is worth being precise about it before anyone
proposes to reuse it. `encrypt`/`decrypt` are Fernet with a key derived by SHA-256 from
`settings.secret_key`, and they protect exactly one thing: the mirror push token on `SkillRepo`. One
key for the whole installation, derived from the same secret that signs sessions — so no rotation, no
per-secret access control, and anything able to read the server's configuration can decrypt
everything ever stored. That is proportionate for a token the server uses on its own behalf. It is
not a vault, and a vault is not that function applied to more rows.

One thing there *is* worth generalising: the API answers `has_token: bool(...)` and never returns the
token itself. That is the correct shape for every secret in the system.

### Whose secret it is — the distinction everything else rests on

* **Personal.** My mailbox password, an API key issued in my name. Not transferable, not readable by
  a manager, not usable by a run somebody else started. In the vault it lives in a space only its
  owner writes to and only their own runs read from.
* **The organisation's.** A service account, a shared key, a token issued to a team rather than to a
  person. Transferable by definition — and the thing that makes both the manager transfer above and
  server-side execution below possible at all.

Without this distinction in the model, "transfer the skill" silently means handing over a colleague's
mailbox, and "run it centrally" means a server holding everybody's passwords. `env_requirements`
already carries `secret: bool`; what it needs is a second field saying *whose*, and the interview
needs to ask — a question a person can genuinely answer, because they know perfectly well whether
they typed their own password or a service account's.

### The rules that make it a vault rather than a table

* **Write-only from the outside.** A value goes in and never comes back out through the API. The
  dashboard shows the name, who set it, when, when it expires and which skill versions declare it —
  never the value. Nobody, its owner included, reads it back; they replace it.
* **Injected at run time, never written down.** The agent asks for the values a version declares as a
  run starts, places them in the process environment and keeps no copy. Generated scripts already
  read from `os.environ`; that becomes a rule rather than a habit — a secret is never written into
  generated source, and never into a `.env` the agent leaves behind.
* **Never into a prompt.** Not the interview, not the transcript, not a `SKILL.md`. This has teeth now
  that an agent assists interviews: an inspection task may report that a `.env` exists and which
  names it defines, and must never report a value. It belongs in the assistant skill's rules,
  alongside *a task with `mode: "inspect"` is read-only*.
* **Every read recorded.** Who, which secret, for which skill version, in which run. Without the log
  a vault is only a database that people trust more than they should.
* **Expiry and rotation are first-class.** A secret can say when it dies, and a replacement value
  reaches every machine that uses it without anybody going to look for them. That is the whole reason
  to centralise it.

### Which vault

The same shape as the storage entry: a narrow port — `set`, `get`, `delete`, `list_names` — with the
backend chosen by configuration.

The default should be **internal**: a `secrets` table with envelope encryption, a data key per secret
wrapped by a key that lives outside the database — a file with restricted permissions, an environment
variable, or a KMS where one exists. It preserves what this project cares about most, that you can
install it on your own machine and need nothing else, and it is already strictly better than today:
the key stops being the session secret, and rotation becomes possible.

The alternative is **OpenBao or HashiCorp Vault**, and it is the right answer for an organisation
already running one — leases, dynamic credentials, an audit device somebody else maintains. It is a
service to operate, which is exactly why it should not be what a first install requires.

Build the port and the internal backend; the external one is then a class, exactly as MinIO is for
the content store.

### What it settles

The handover checklist stops saying "here are the names, go and find the values" for the half of them
that never belonged to a person. Central execution gains somewhere to obtain credentials that is not
a copy of somebody's laptop. Rotation becomes one write instead of a search. And "who can still get
into that system now they have left" stops being a question nobody in the room can answer.

## Running a task on the server instead of a laptop

Skills run today where the person is: the agent on their machine executes the steps, the companion
reports the runs. That is the right default — the files are there, the credentials are there — and
it stops working in exactly the case above. A holiday, a laptop that is off, a task that must run at
three in the morning: there is nobody's machine to run it on.

Running centrally means moving three things to a place the server controls: the **skill**, whose
package is already in the content store and needs only somewhere to be unpacked; the **scripts or
MCP server**, already generated per version (`McpServerVersion`, `runtime` telling which shape); and
an **executor** — a sandbox with the runtime, the allowed packages
(`services/mcpgen/generator.py::ALLOWED_PIP`) and no more reach than the step needs.

The questions to answer before writing any of it:

* **The data is not there.** A step that opens a spreadsheet in someone's Documents folder cannot
  run on a server. Central execution suits steps that act on shared systems — a database, a mailbox,
  an API — and the analysis in `services/delivery.py` already knows how to tell steps apart. It
  would need to answer a second question: not only "script or MCP", but "where can this run at all".
* **The credentials would have to move.** Everything the previous entry says about not handing over
  a person's secrets applies here twice over: a server that runs tasks for many people holds many
  people's access. That is a different product with a different risk, and it should be entered
  deliberately — service accounts owned by the organisation, not a copy of somebody's password,
  which is precisely the distinction the vault entry above exists to make enforceable.
* **Who authorises an irreversible step at three in the morning?** The checkpoint machinery assumes
  a person is watching (`services/tester/checkpoints.py`). Unattended runs need a decision taken in
  advance and bounded: this step, on this data, up to this size, otherwise stop and wait for
  morning. `auto_confirm_after_confirmations` is the seed of that idea; unattended execution would
  need it to become explicit rather than a count of past successes.

This overlaps with **remote MCP servers** above, and the two should be designed together: the same
sandbox, the same authorisation, the same lifecycle. Central execution is that infrastructure with a
scheduler in front of it.

## Seeing across people: what a team has automated

Everything today is seen one skill at a time, from inside a project. That is right for the person
building a skill and useless for whoever has to look after a team: there is no way to ask what has
been automated, by whom, what is failing, or what would stop working if one person left.

**The obstacle to clear first.** There is no organisational model. `Project` has members with roles
(`owner`, `editor`, `viewer`) and that is all — no team, no "manages", no hierarchy. Before any
management view is designed, one decision has to be made: is a project the team, with a manager
being simply an owner, or does an organisation belong above projects? The first is far cheaper and
probably enough; the second is a different product. Nothing else here should be built before that
answer exists.

### Grouping, which is a table

Skills carry `category_id`, `tags` and `created_by` — enough to group by category, then by person,
then by tag, in any order the reader chooses, with counts and filters. This is a list with
configurable grouping, and it should be built as one: sortable, countable, exportable. Presenting it
as a graph would make it prettier and harder to read.

### The graph, which is about relationships

A graph earns its place only where the edges mean something, and there are real ones already
recorded:

* `Skill.forked_from_skill_id` — who derived their skill from whose.
* `data_sources[].ref` and `integrations[].system` in the knowledge document — skills that touch the
  same file, mailbox, database or API.
* shared library components (`services/library/catalog.py`) — skills built on the same tools.

That graph answers what no table can: *if this spreadsheet changes shape, how many skills break?
who else reaches into the CRM? which automations depend on the one system nobody has documented?*
It is worth building, and it is a different feature from the grouping above — not a prettier version
of it.

### Runs, seen across skills

The per-run view exists: every step expands with the action performed, the tool, inputs and outputs.
What is missing is the same data aggregated — by person, by team, by period — with the questions a
reader actually arrives with: what failed this week, what is slower than it was, what nobody has run
in two months. `Run` already carries `status`, `duration_ms`, `human_feedback` (`ok` / `corrected` /
`wrong`) and `is_golden`; none of it is aggregated anywhere today.

### Three things worth more than the visualisation

**Measure what it saves.** The system records how long a run took and has no idea how long the task
took by hand — so it cannot say whether any of this is worth doing. One question in the interview
("how long does this take you each time, and how often?") plus the runs already logged gives the
number the whole product is judged on. It is a field in the knowledge document and a subtraction.

**Find the duplicated work.** Two colleagues automating the same task without knowing about each
other is the normal state of a large team. It is detectable with data already held: skills whose
data sources and integrations overlap heavily are probably the same job done twice. Surfacing that
is worth more than any chart.

**Show what depends on one person.** Which skills only one person runs, which touch a system only
one person can reach, which have never been handed over. This is the same question as handing work
over, asked before the holiday rather than during it, and the data — installations per user, runs
per user — is already there.
