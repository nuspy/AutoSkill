// The only piece that may speak to the machine, and it does nothing on its own initiative.
//
// A request arrives from a content script running on an AutoSkill page, is forwarded to the native
// messaging host, and its answers are relayed back. The service worker keeps no credentials and makes
// no server calls: the page already holds the person's session, so anything reaching AutoSkill goes
// through the page. What the worker owns is the one thing a page cannot have — the native port.

const HOST = "com.autoskill.host";

/** One port per request rather than a shared connection.
 *
 * `sendNativeMessage` would be shorter, but it delivers a single reply and an install has a lot to
 * say before it is finished. A connection per request also means a host that dies takes one operation
 * with it instead of every operation in flight. */
function run(request, onMessage) {
  return new Promise((resolve, reject) => {
    let port;
    try {
      port = chrome.runtime.connectNative(HOST);
    } catch (err) {
      reject(new Error(`native host unavailable: ${err.message}`));
      return;
    }
    let settled = false;
    port.onMessage.addListener((message) => {
      if (message.kind === "progress") {
        onMessage(message);
        return;
      }
      settled = true;
      port.disconnect();
      if (message.kind === "error") reject(Object.assign(new Error(message.message), message));
      else resolve(message.result);
    });
    port.onDisconnect.addListener(() => {
      if (settled) return;
      // The commonest cause by far is that the host is not registered on this machine, which is a
      // thing the page should say plainly rather than a failure it should retry.
      const err = chrome.runtime.lastError;
      reject(Object.assign(new Error(err?.message ?? "native host closed the connection"), { code: "host_unreachable" }));
    });
    port.postMessage(request);
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Only from a tab, and only from a page this extension was granted. `sender.tab` is set by the
  // browser and cannot be forged by the page.
  if (!sender.tab || message?.channel !== "autoskill") return undefined;
  run({ id: message.id, op: message.op, params: message.params ?? {} }, (progress) => {
    chrome.tabs.sendMessage(sender.tab.id, { channel: "autoskill", id: message.id, ...progress }).catch(() => {});
  }).then(
    (result) => sendResponse({ ok: true, result }),
    (error) => sendResponse({ ok: false, code: error.code ?? "error", message: error.message, details: error.details }),
  );
  return true; // the answer comes later
});
