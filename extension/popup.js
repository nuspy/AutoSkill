// What this machine looks like, straight from the native host. Read-only: the popup asks and shows.
const out = document.getElementById("out");

function line(html) {
  const div = document.createElement("div");
  div.className = "row";
  div.innerHTML = html;
  return div;
}

function escape(s) {
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

chrome.runtime.sendMessage({ channel: "autoskill", id: 1, op: "state" }, (reply) => {
  const failure = chrome.runtime.lastError;
  out.textContent = "";
  if (failure || !reply?.ok) {
    // Almost always "the host is not registered here", which the installer is what fixes.
    out.append(line(`<span class="bad">${escape(failure?.message ?? reply?.message ?? "no answer")}</span>`));
    out.append(line('<span class="muted">Install the AutoSkill helper from the app, then reopen this.</span>'));
    return;
  }
  const s = reply.result;
  out.append(line(`<span class="muted">server</span> <code>${escape(s.server_url ?? "—")}</code>`));
  out.append(line(`<span class="muted">signed in</span> ${s.logged_in ? "yes" : "no"} · CLI ${escape(s.cli_version)}`));
  for (const a of s.agents) {
    out.append(
      line(
        `${a.detected ? "✓" : "·"} <strong>${escape(a.display_name)}</strong>` +
          `<span class="muted"> ${escape(a.base_source)}${a.companion ? ` · companion ${escape(a.companion)}` : ""}</span>`,
      ),
    );
  }
  if (s.trials.length) {
    out.append(line(`<span class="muted">open trials</span> ${s.trials.map((t) => escape(t.skill)).join(", ")}`));
  }
});
