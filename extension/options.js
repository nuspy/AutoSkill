// Where the person names their own AutoSkill, because most installations are not on localhost.
//
// The permission is asked for at this moment, from a click, and for that origin alone. The manifest
// therefore ships with only the development addresses in `host_permissions`: an extension that asks
// for every site up front is one nobody should install, whatever it promises to do with the access.

const url = document.getElementById("url");
const status = document.getElementById("status");

function originOf(value) {
  try {
    const parsed = new URL(value);
    if (parsed.protocol !== "https:" && parsed.hostname !== "localhost") return null;
    return `${parsed.origin}/*`;
  } catch {
    return null;
  }
}

chrome.storage.local.get("serverUrl").then(({ serverUrl }) => {
  if (serverUrl) url.value = serverUrl;
});

url.addEventListener("change", async () => {
  const pattern = originOf(url.value.trim());
  if (!pattern) {
    status.textContent = "That is not an address I can use — https, or localhost while developing.";
    return;
  }
  // Asked from the change event so it counts as a user gesture; Chrome refuses otherwise.
  const granted = await chrome.permissions.request({ origins: [pattern] });
  if (!granted) {
    status.textContent = "Not granted, so nothing changed.";
    return;
  }
  await chrome.storage.local.set({ serverUrl: url.value.trim() });
  await chrome.scripting.registerContentScripts([
    { id: `autoskill-${pattern}`, matches: [pattern], js: ["content.js"], runAt: "document_start" },
  ]).catch(() => {}); // already registered is not a failure worth showing
  status.textContent = "Saved. Reload your AutoSkill tab.";
});
