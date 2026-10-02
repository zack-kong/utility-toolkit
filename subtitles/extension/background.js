const SESSION_KEY = "activeSession";
const NATIVE_HOST = "com.video_auto_translate.host";
const cueTranslations = new Map();

async function translateTrackCue(original, language, targetLanguage = "zh") {
  const { token, glossary, termPackEnabled } = await chrome.storage.local.get({
    token: "", glossary: "", termPackEnabled: true });
  const key = `${language}\n${targetLanguage}\n${original}\n${glossary}\n${termPackEnabled}`;
  if (cueTranslations.has(key)) return cueTranslations.get(key);
  const work = (async () => {
    const response = await fetch("http://127.0.0.1:8765/api/translate-cue", {
      method: "POST", headers: { "Content-Type": "application/json", "X-Vat-Token": token },
      body: JSON.stringify({ text: original, language, target_language: targetLanguage,
        glossary, term_pack_enabled: termPackEnabled }),
    });
    if (!response.ok) throw new Error(`Caption translation failed (HTTP ${response.status}).`);
    return (await response.json()).translation;
  })();
  cueTranslations.set(key, work);
  work.catch(() => { if (cueTranslations.get(key) === work) cueTranslations.delete(key); });
  if (cueTranslations.size > 64) cueTranslations.delete(cueTranslations.keys().next().value);
  return work;
}

async function getSession() {
  return (await chrome.storage.session.get(SESSION_KEY))[SESSION_KEY] ?? null;
}

async function ensureOffscreen() {
  const contexts = await chrome.runtime.getContexts({});
  if (!contexts.some((context) => context.contextType === "OFFSCREEN_DOCUMENT")) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA"],
      justification: "Capture active tab audio for local speech recognition.",
    });
  }
}

async function ensureLocalService(storedToken) {
  try {
    const response = await chrome.runtime.sendNativeMessage(NATIVE_HOST, { command: "ensure_running" });
    if (!response?.ok || !response.token) {
      throw new Error(response?.error || "The native helper did not return a service token.");
    }
    await chrome.storage.local.set({ token: response.token });
    return response.token;
  } catch (error) {
    if (storedToken) {
      try {
        const health = await fetch("http://127.0.0.1:8765/health", {
          headers: { "X-Vat-Token": storedToken },
        });
        if (health.ok) return storedToken;
      } catch { /* The manually started service is unavailable. */ }
    }
    await chrome.runtime.openOptionsPage();
    throw new Error(`Could not start the local service: ${error.message}. Check Native Messaging registration.`);
  }
}

async function start(tab) {
  const preferences = await chrome.storage.local.get({
    token: "", mode: "accurate", audioMode: "dialogue", sourceLanguage: "auto",
    targetLanguage: "zh", glossary: "", termPackEnabled: true,
  });
  const token = await ensureLocalService(preferences.token);
  let track = await chrome.tabs.sendMessage(tab.id, { type: "vat:probe-track" }).catch(() => null);
  if (!track) {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["content.js"] });
    track = await chrome.tabs.sendMessage(tab.id, { type: "vat:probe-track" }).catch(() => null);
  }
  let source = track?.available ? "track" : "audio";
  const session = {
    id: crypto.randomUUID(), tabId: tab.id, epoch: 0,
    mode: preferences.mode, audioMode: preferences.audioMode,
    sourceLanguage: preferences.sourceLanguage, targetLanguage: preferences.targetLanguage,
    glossary: preferences.glossary, termPackEnabled: preferences.termPackEnabled, source,
  };
  await chrome.storage.session.set({ [SESSION_KEY]: session });
  await chrome.tabs.sendMessage(tab.id, { type: "vat:clear", epoch: 0 });
  if (source === "track") {
    const confirmation = await chrome.tabs.sendMessage(tab.id, { type: "vat:track-start", epoch: 0 });
    if (!confirmation?.active) {
      source = "audio";
      session.source = source;
      await chrome.storage.session.set({ [SESSION_KEY]: session });
    }
  }
  if (source === "audio") {
    await ensureOffscreen();
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
    await chrome.runtime.sendMessage({
      target: "offscreen", type: "vat:start", streamId, session, token,
    });
  } else {
    await chrome.tabs.sendMessage(tab.id, { type: "vat:status",
      message: "Using the site's captions for local translation. Open History to pause and read." }).catch(() => {});
  }
}

async function stop() {
  const session = await getSession();
  if (!session) return;
  await chrome.storage.session.remove(SESSION_KEY);
  cueTranslations.clear();
  if (session.source === "track") {
    await chrome.tabs.sendMessage(session.tabId, { type: "vat:track-stop" }).catch(() => {});
  } else {
    await chrome.runtime.sendMessage({ target: "offscreen", type: "vat:stop" }).catch(() => {});
  }
  await chrome.tabs.sendMessage(session.tabId, { type: "vat:hide" }).catch(() => {});
}

chrome.action.onClicked.addListener(async (tab) => {
  try {
    const session = await getSession();
    if (session?.tabId === tab.id) await stop();
    else {
      if (session) await stop();
      await start(tab);
    }
  } catch (error) {
    await chrome.tabs.sendMessage(tab.id, { type: "vat:status", state: "error", message: error.message }).catch(() => {});
  }
});

chrome.runtime.onMessage.addListener((message, sender) => {
  if (message.target === "background" && message.type === "vat:stop-request") {
    void (async () => {
      const session = await getSession();
      if (sender.tab?.id === session?.tabId) await stop();
      else if (!session && sender.tab?.id !== undefined) {
        await chrome.tabs.sendMessage(sender.tab.id, { type: "vat:hide" }).catch(() => {});
      }
    })();
    return;
  }
  if (message.target === "background" && message.type === "vat:ended") {
    void (async () => {
      const session = await getSession();
      if (!session || message.session_id !== session.id) return;
      await chrome.tabs.sendMessage(session.tabId, {
        type: "vat:clear", epoch: session.epoch + 1,
      }).catch(() => {});
      await chrome.tabs.sendMessage(session.tabId, {
        type: "vat:error", message: message.message || "Audio capture stopped.",
      }).catch(() => {});
      await chrome.storage.session.remove(SESSION_KEY);
    })();
    return;
  }
  if (message.target === "background" && message.type === "vat:video-event") {
    void (async () => {
      const session = await getSession();
      if (!session || sender.tab?.id !== session.tabId) return;
      if (message.event === "playing") {
        if (session.source !== "track") {
          await chrome.runtime.sendMessage({ target: "offscreen", type: "vat:playing" });
        }
        return;
      }
      if (message.event === "pause") {
        if (session.source !== "track") {
          await chrome.runtime.sendMessage({ target: "offscreen", type: "vat:pause" });
        }
        await chrome.tabs.sendMessage(session.tabId, { type: "vat:hold", epoch: session.epoch }).catch(() => {});
        return;
      }
      if (!["seeking", "ended"].includes(message.event)) return;
      const next = { ...session, epoch: session.epoch + 1 };
      await chrome.storage.session.set({ [SESSION_KEY]: next });
      if (session.source !== "track") {
        await chrome.runtime.sendMessage({ target: "offscreen", type: "vat:reset", epoch: next.epoch,
          paused: message.event === "ended" });
      }
      await chrome.tabs.sendMessage(next.tabId, {
        type: "vat:clear", epoch: next.epoch,
      }).catch(() => {});
    })();
  }
  if (message.target === "background" && message.type === "vat:configure-language") {
    void (async () => {
      const session = await getSession();
      if (!session || sender.tab?.id !== session.tabId) return;
      if (!["auto", "en", "ja", "ko", "es"].includes(message.sourceLanguage)
          || !["zh", "en", "ja", "ko", "es"].includes(message.targetLanguage)) return;
      const next = { ...session, epoch: session.epoch + 1,
        sourceLanguage: message.sourceLanguage, targetLanguage: message.targetLanguage };
      await chrome.storage.session.set({ [SESSION_KEY]: next });
      cueTranslations.clear();
      await chrome.tabs.sendMessage(next.tabId, { type: "vat:clear", epoch: next.epoch }).catch(() => {});
      if (next.source === "track") {
        await chrome.tabs.sendMessage(next.tabId, { type: "vat:track-refresh" }).catch(() => {});
      } else {
        await chrome.runtime.sendMessage({ target: "offscreen", type: "vat:configure", epoch: next.epoch,
          sourceLanguage: next.sourceLanguage, targetLanguage: next.targetLanguage }).catch(() => {});
      }
    })();
    return;
  }
  if (message.target === "background" && message.type === "vat:cue") {
    void (async () => {
      const session = await getSession();
      if (session?.source !== "track" || sender.tab?.id !== session.tabId || message.epoch !== session.epoch) return;
      const original = String(message.original || "").trim().slice(0, 1000);
      const language = session.sourceLanguage && session.sourceLanguage !== "auto"
        ? session.sourceLanguage : String(message.language || "");
      const speaker = /^[ABC]$/.test(message.speaker || "") ? message.speaker : undefined;
      if (!original) return;
      const caption = { type: "vat:subtitle", epoch: session.epoch, utterance_id: message.utterance_id,
        original, translation: "", speaker, final: true };
      await chrome.tabs.sendMessage(session.tabId, caption).catch(() => {});
      try {
        const translation = await translateTrackCue(original, language, session.targetLanguage || "zh");
        const current = await getSession();
        if (current?.id !== session.id || current.epoch !== session.epoch) return;
        await chrome.tabs.sendMessage(session.tabId, { ...caption, translation }).catch(() => {});
      } catch (error) {
        if ((await getSession())?.id === session.id) {
          await chrome.tabs.sendMessage(session.tabId, { type: "vat:status", message: error.message }).catch(() => {});
        }
      }
    })();
    return;
  }
  if (message.target === "background" && message.type === "vat:prefetch-cue") {
    void (async () => {
      const session = await getSession();
      if (session?.source !== "track" || sender.tab?.id !== session.tabId || message.epoch !== session.epoch) return;
      const original = String(message.original || "").trim().slice(0, 1000);
      const language = session.sourceLanguage && session.sourceLanguage !== "auto"
        ? session.sourceLanguage : String(message.language || "");
      if (original) await translateTrackCue(original, language, session.targetLanguage || "zh").catch(() => {});
    })();
    return;
  }
  if (message.target === "background" && ["subtitle", "status", "error"].includes(message.type)) {
    void (async () => {
      const session = await getSession();
      if (!session) return;
      if (message.epoch !== undefined && message.epoch !== session.epoch) return;
      await chrome.tabs.sendMessage(session.tabId, { ...message, type: `vat:${message.type}` }).catch(() => {});
    })();
  }
});

chrome.tabs.onRemoved.addListener((tabId) => {
  void (async () => { if ((await getSession())?.tabId === tabId) await stop(); })();
});
