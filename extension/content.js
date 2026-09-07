// The bridge between the page and the extension, and the narrowest thing that can be one.
//
// It relays two kinds of message and nothing else. Every guard here is because a content script runs
// inside a page it does not control: `window.postMessage` is readable and writable by any script on
// the origin, and by any frame that can reach it.

const CHANNEL = "autoskill";

/** Announce the extension so the page can offer the button — and only then.
 *
 * The page renders the command either way; what it must not do is offer to run something it cannot
 * run. So the flag is set here rather than assumed there, and it is a plain marker, not an API: a
 * page script cannot be handed a function that would let any other script on the origin call it. */
function announce() {
  document.documentElement.dataset.autoskillExtension = chrome.runtime.getManifest().version;
}
announce();
document.addEventListener("DOMContentLoaded", announce);

window.addEventListener("message", (event) => {
  // Same window, same origin, top frame. A message from an embedded frame is not this page asking.
  if (event.source !== window || event.origin !== window.location.origin) return;
  if (window.top !== window) return;
  const data = event.data;
  if (!data || data.channel !== CHANNEL || data.direction !== "request") return;
  if (typeof data.op !== "string" || typeof data.id !== "number") return;

  chrome.runtime.sendMessage({ channel: CHANNEL, id: data.id, op: data.op, params: data.params }, (reply) => {
    const error = chrome.runtime.lastError;
    window.postMessage(
      error
        ? { channel: CHANNEL, direction: "response", id: data.id, ok: false, code: "extension_error", message: error.message }
        : { channel: CHANNEL, direction: "response", id: data.id, ...reply },
      window.location.origin,
    );
  });
});

// Progress travels the other way, from the worker to the page, while an operation is still running.
chrome.runtime.onMessage.addListener((message) => {
  if (message?.channel !== CHANNEL) return;
  window.postMessage({ ...message, direction: "progress" }, window.location.origin);
});
