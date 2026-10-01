const defaults = { token: "", mode: "accurate", sourceLanguage: "auto", targetLanguage: "zh",
  audioMode: "dialogue", showOriginal: true,
  showTranslation: true, fontSize: 25, position: "bottom", visibleCaptions: 2, overlayX: 50, overlayY: 80,
  glossary: "", termPackEnabled: true };
const ids = Object.keys(defaults).filter((id) => !["overlayX", "overlayY"].includes(id));
const status = document.querySelector("#status");

function show(value) { status.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2); }
function values() { return Object.fromEntries(ids.map((id) => [id, document.querySelector(`#${id}`).type === "checkbox" ? document.querySelector(`#${id}`).checked : document.querySelector(`#${id}`).value])); }
async function tokenHeader() { return { "X-Vat-Token": document.querySelector("#token").value }; }
function glossaryError(raw) {
  if (raw.length > 4000) return "The glossary cannot exceed 4,000 characters.";
  let count = 0;
  for (const entry of raw.split(/\r?\n/)) {
    const line = entry.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 0) return `Invalid entry: ${line}. Use "source = Chinese translation".`;
    let source = line.slice(0, separator).trim();
    const target = line.slice(separator + 1).trim();
    if (source.includes("|")) {
      const parts = source.split("|", 2);
      if (!["ja", "en", "ko", "es", "fr", "de", "zh"].includes(parts[0].trim())) return "Unsupported glossary language prefix.";
      source = parts[1].trim();
    }
    if (!source || !target || source.length > 80 || target.length > 80) return "Source and translation must be nonempty and no longer than 80 characters each.";
    if (++count > 60) return "The glossary supports at most 60 entries.";
  }
  return "";
}

const stored = await chrome.storage.local.get(defaults);
for (const id of ids) { const element = document.querySelector(`#${id}`); element.type === "checkbox" ? element.checked = stored[id] : element.value = stored[id]; }
document.querySelector("#save").addEventListener("click", async () => {
  const preferences = values();
  const error = glossaryError(preferences.glossary);
  if (error) { show(error); return; }
  await chrome.storage.local.set(preferences); show("Settings saved. Language defaults apply to the next session; switch languages in the caption bar during playback. New terms apply to the next web caption; restart an audio session to apply them.");
});
document.querySelector("#health").addEventListener("click", async () => {
  try { show(await (await fetch("http://127.0.0.1:8765/health", { headers: await tokenHeader() })).json()); } catch { show("Cannot connect to the local service. Start python -m server.app.main."); }
});
document.querySelector("#download").addEventListener("click", async () => {
  if (!confirm("Download Whisper, Hy-MT2, and the local inference runtime? Allow about 5 GB of disk space. Hy-MT2 is licensed under Apache-2.0. Continue?")) return;
  try { show(await (await fetch("http://127.0.0.1:8765/api/models/download", { method: "POST", headers: await tokenHeader() })).json()); }
  catch { show("Could not start the download. Check the local service and token."); }
});
