# The AutoSkill browser extension

Lets an AutoSkill page install skills, run trials and remove them on the machine you are looking at
it from, instead of printing a command for you to carry to a terminal.

It does not do any of that itself. **A browser extension cannot write to `~/.hermes/skills/` and
cannot start a process** — that is the sandbox, not a missing API — so this talks to a *native
messaging host*, `autoskill-native-host`, which is part of `autoskill-local` and does the work by
calling the same functions the `autoskill` commands call.

```
page ──postMessage── content.js ──port── background.js ──native messaging── autoskill-native-host
```

## Installing it

Normally you do not install this by hand: **My devices** in AutoSkill offers a setup script that
installs the CLI, registers the host and unpacks this folder for you. What the script cannot do is the
last click — Chrome has not allowed an extension to be installed from a local file since version 33 —
so it tells you to open `chrome://extensions`, turn on Developer mode, and load the unpacked folder.

To work on the extension itself:

1. `chrome://extensions` → Developer mode → **Load unpacked** → this directory.
2. Register the host for the id Chrome shows:
   ```
   autoskill browser install --extension-id <id>
   ```
   With the pinned `key` below the id is always the same, so this is a one-off.

## The pinned key

`manifest.json` carries a `key`, which fixes the extension id at
`cnkodldlkekifpmakgkkmpdikbobbjff`. Without it Chrome derives a different id on every machine, and
neither the host's allow-list nor the server's setup script could name the extension they are pairing
with. Three places hold that id — the manifest, `nativehost.EXTENSION_IDS`, and the server's
`extension_id` setting — and two tests fail if they stop agreeing.

The private half of that key is not in this repository and is not needed to load the extension
unpacked; it would only be needed to sign a `.crx`.

## What it may do, and what it may not

* The content script runs **only** on the AutoSkill origin, and relays a message only when it came
  from the same window, the same origin and the top frame.
* Nothing is injected into the page. An injected bridge would be callable by every script on the
  origin; a filtered message is not.
* The extension holds **no credentials**. The page already has the person's session, so anything that
  reaches the AutoSkill server goes through the page.
* The host exposes a closed set of operations. None of them takes a shell command, a path to write or
  a URL to run — and it refuses any caller that is not this extension.
