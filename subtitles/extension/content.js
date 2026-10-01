(() => {
  const previous = globalThis.__vatContentInstalled;
  if (previous?.version === 2 && previous.active) return;
  previous?.dispose?.();
  const installation = { version: 2, active: true, dispose() { this.active = false; } };
  globalThis.__vatContentInstalled = installation;

  function handleExtensionError(error) {
    if (String(error?.message || error).includes("Extension context invalidated")) installation.dispose();
  }

  function sendToBackground(message) {
    if (!installation.active) return;
    try {
      const result = chrome.runtime.sendMessage(message);
      result?.catch?.(handleExtensionError);
    } catch (error) { handleExtensionError(error); }
  }

  function savePreferences(values) {
    if (!installation.active) return;
    try {
      const result = chrome.storage.local.set(values);
      result?.catch?.(handleExtensionError);
    } catch (error) { handleExtensionError(error); }
  }

  if (window !== window.top) {
    const observed = new WeakSet();
    const trackFrameVideos = () => {
      for (const video of document.querySelectorAll("video")) {
        if (observed.has(video)) continue;
        observed.add(video);
        for (const event of ["seeking", "pause", "playing", "ended"]) {
          video.addEventListener(event, () => sendToBackground({
            target: "background", type: "vat:video-event", event,
          }));
        }
      }
    };
    const frameObserver = new MutationObserver(trackFrameVideos);
    frameObserver.observe(document.documentElement, { childList: true, subtree: true });
    installation.dispose = () => { installation.active = false; frameObserver.disconnect(); };
    trackFrameVideos();
    return;
  }

  let epoch = 0;
  let host = null;
  let captionList = null;
  let historyPanel = null;
  let historyList = null;
  let historyButton = null;
  let sourceSelect = null;
  let targetSelect = null;
  let status = null;
  let trackedVideo = null;
  let selectedTrack = null;
  let selectedTrackMode = null;
  let trackSequence = 0;
  let activeCueKeys = new Set();
  let prefetchedCueKeys = new Set();
  const trackSpeakers = new Map();
  let observer = null;
  let activeUtterance = -1;
  let captions = [];
  let history = [];
  let preferences = { showOriginal: true, showTranslation: true, fontSize: 25,
    position: "bottom", overlayX: 50, overlayY: 80, visibleCaptions: 2,
    sourceLanguage: "auto", targetLanguage: "zh" };
  const maxVisibleCaptions = 3;

  installation.dispose = () => {
    if (!installation.active) return;
    installation.active = false;
    observer?.disconnect();
    stopTrack();
    host?.remove?.();
  };

  function activeVideo() {
    const videos = [...document.querySelectorAll("video")];
    return videos.sort((a, b) => (b.clientWidth * b.clientHeight) - (a.clientWidth * a.clientHeight))[0] ?? null;
  }

  function availableTrack() {
    const video = activeVideo();
    if (!video?.textTracks) return null;
    return [...video.textTracks].find((track) =>
      ["subtitles", "captions"].includes(track.kind) && track.mode !== "disabled" && track.language);
  }

  function onCueChange() {
    if (!selectedTrack) return;
    const currentKeys = new Set();
    for (const cue of [...(selectedTrack.activeCues || [])]) {
      const raw = String(cue.text || "");
      const voice = raw.match(/<v\s+([^>]+)>/i)?.[1]?.trim();
      if (voice && !trackSpeakers.has(voice) && trackSpeakers.size < 3) {
        trackSpeakers.set(voice, String.fromCharCode(65 + trackSpeakers.size));
      }
      const speaker = voice ? trackSpeakers.get(voice) : undefined;
      const original = raw.replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
      const key = `${cue.startTime}:${cue.endTime}:${original}`;
      currentKeys.add(key);
      if (original && !activeCueKeys.has(key)) sendToBackground({ target: "background", type: "vat:cue",
        epoch, utterance_id: trackSequence++, original, language: selectedTrack.language, speaker });
    }
    activeCueKeys = currentKeys;
    const future = [...(selectedTrack.cues || [])].filter((cue) =>
      cue.startTime > (trackedVideo?.currentTime ?? 0) &&
      cue.startTime <= (trackedVideo?.currentTime ?? 0) + 30).slice(0, 3);
    for (const cue of future) {
      const original = String(cue.text || "").replace(/<[^>]*>/g, "").replace(/\s+/g, " ").trim();
      const key = `${cue.startTime}:${cue.endTime}:${original}`;
      if (!original || prefetchedCueKeys.has(key)) continue;
      prefetchedCueKeys.add(key);
      sendToBackground({ target: "background", type: "vat:prefetch-cue",
        epoch, original, language: selectedTrack.language });
    }
  }

  function stopTrack() {
    if (!selectedTrack) return;
    selectedTrack.removeEventListener("cuechange", onCueChange);
    if (selectedTrack.mode === "hidden" && selectedTrackMode === "showing") {
      selectedTrack.mode = "showing";
    }
    selectedTrack = null;
    selectedTrackMode = null;
    activeCueKeys.clear();
    prefetchedCueKeys.clear();
    trackSpeakers.clear();
  }

  function ensureOverlay() {
    if (host?.isConnected) return;
    document.getElementById?.("vat-subtitle-host")?.remove();
    host = document.createElement("div");
    host.id = "vat-subtitle-host";
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      :host { all: initial; position: fixed; left: 50%; bottom: 9%; transform: translateX(-50%); z-index: 2147483647; pointer-events: none; width: min(86vw, 1000px); text-align: center; }
      .caption { margin-top: 8px; }
      .line { color: white; font: 600 var(--vat-size, 25px)/1.42 system-ui, sans-serif; text-shadow: 0 2px 4px #000, 0 0 8px #000; padding: 0 8px; overflow-wrap: anywhere; }
      .tentative { opacity: .62; }
      .speaker { display: inline-block; padding: 1px 7px; border-radius: 4px; background: #1b457a;
        color: white; font: 700 14px system-ui, sans-serif; }
      .translation { color: #ffe69b; } .status { margin-top: 6px; color: #ddd; font: 12px system-ui, sans-serif; text-shadow: 0 1px 3px #000; }
      .tools { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px;
        max-width: 100%; pointer-events: auto; }
      button { background: #202430; color: white; border: 1px solid #777; border-radius: 5px; padding: 5px 9px; cursor: pointer; font: 13px system-ui, sans-serif; }
      .language-bar { display: inline-flex; gap: 4px; }
      .language-bar select { background: #202430; color: white; border: 1px solid #777; border-radius: 5px;
        padding: 5px 4px; font: 13px system-ui, sans-serif; }
      .history { pointer-events: auto; max-height: 42vh; overflow-y: auto; margin: 6px 0; padding: 10px;
        border-radius: 8px; background: rgba(12, 15, 22, .94); text-align: left; }
      .history .caption { border-bottom: 1px solid #555; padding: 6px 0; }
      .history .line { font-size: min(var(--vat-size, 25px), 20px); }
      [hidden] { display: none; }
    `;
    captionList = document.createElement("div");
    const tools = document.createElement("div"); tools.className = "tools";
    const dragButton = document.createElement("button"); dragButton.textContent = "⠿ Drag";
    let dragOffsetX = 0;
    let dragOffsetY = 0;
    dragButton.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      const rect = host.getBoundingClientRect();
      dragOffsetX = event.clientX - (rect.left + rect.width / 2);
      dragOffsetY = event.clientY - (rect.top + rect.height / 2);
      dragButton.setPointerCapture(event.pointerId);
    });
    dragButton.addEventListener("pointermove", (event) => {
      if (!dragButton.hasPointerCapture(event.pointerId)) return;
      const rect = host.getBoundingClientRect();
      const width = window.innerWidth;
      const height = window.innerHeight;
      const x = Math.min(width - rect.width / 2, Math.max(rect.width / 2, event.clientX - dragOffsetX));
      const y = Math.min(height - rect.height / 2, Math.max(rect.height / 2, event.clientY - dragOffsetY));
      preferences.position = "custom";
      preferences.overlayX = 100 * x / width;
      preferences.overlayY = 100 * y / height;
      positionOverlay();
    });
    dragButton.addEventListener("pointerup", (event) => {
      if (!dragButton.hasPointerCapture(event.pointerId)) return;
      dragButton.releasePointerCapture(event.pointerId);
      savePreferences({ position: "custom", overlayX: preferences.overlayX,
        overlayY: preferences.overlayY });
    });
    const smallerButton = document.createElement("button"); smallerButton.textContent = "A−";
    const largerButton = document.createElement("button"); largerButton.textContent = "A+";
    const changeSize = (delta) => {
      preferences.fontSize = Math.max(14, Math.min(48, Number(preferences.fontSize) + delta));
      host.style.setProperty("--vat-size", `${preferences.fontSize}px`);
      savePreferences({ fontSize: preferences.fontSize });
    };
    smallerButton.addEventListener("click", () => changeSize(-2));
    largerButton.addEventListener("click", () => changeSize(2));
    historyButton = document.createElement("button"); historyButton.textContent = "History · pause to read";
    historyButton.hidden = true;
    historyButton.addEventListener("click", () => {
      historyPanel.hidden = !historyPanel.hidden;
      historyButton.textContent = historyPanel.hidden ? "History · pause to read" : "Close history";
      if (!historyPanel.hidden) trackedVideo?.pause();
    });
    tools.append(dragButton, smallerButton, largerButton, historyButton);
    const languageBar = document.createElement("span"); languageBar.className = "language-bar";
    const makeSelect = (label, choices) => {
      const select = document.createElement("select"); select.setAttribute?.("aria-label", label);
      for (const [value, name] of choices) {
        const option = document.createElement("option"); option.value = value; option.textContent = name;
        select.append(option);
      }
      return select;
    };
    sourceSelect = makeSelect("Source language", [["auto", "Source: Auto"], ["en", "Source: English"],
      ["ja", "Source: Japanese"], ["ko", "Source: Korean"], ["es", "Source: Spanish"]]);
    targetSelect = makeSelect("Target language", [["zh", "To: Chinese"], ["en", "To: English"],
      ["ja", "To: Japanese"], ["ko", "To: Korean"], ["es", "To: Spanish"]]);
    const changeLanguage = () => {
      preferences.sourceLanguage = sourceSelect.value;
      preferences.targetLanguage = targetSelect.value;
      savePreferences({ sourceLanguage: preferences.sourceLanguage, targetLanguage: preferences.targetLanguage });
      sendToBackground({ target: "background", type: "vat:configure-language",
        sourceLanguage: preferences.sourceLanguage, targetLanguage: preferences.targetLanguage });
    };
    sourceSelect.addEventListener("change", changeLanguage);
    targetSelect.addEventListener("change", changeLanguage);
    languageBar.append(sourceSelect, targetSelect); tools.append(languageBar);
    const closeButton = document.createElement("button"); closeButton.textContent = "Close captions";
    closeButton.setAttribute?.("aria-label", "Close captions and stop translation");
    closeButton.addEventListener("click", () => sendToBackground({ target: "background", type: "vat:stop-request" }));
    tools.append(closeButton);
    historyPanel = document.createElement("div"); historyPanel.className = "history"; historyPanel.hidden = true;
    historyList = document.createElement("div"); historyPanel.append(historyList);
    status = document.createElement("div"); status.className = "status"; status.hidden = true;
    shadow.append(style, captionList, tools, historyPanel, status);
    const fullscreen = document.fullscreenElement;
    (fullscreen && fullscreen.tagName !== "VIDEO" ? fullscreen : document.documentElement).append(host);
  }

  function positionOverlay() {
    if (preferences.position === "custom") {
      host.style.left = `${preferences.overlayX}%`;
      host.style.top = `${preferences.overlayY}%`;
      host.style.bottom = "auto";
      host.style.transform = "translate(-50%, -50%)";
    } else {
      host.style.left = "50%";
      host.style.top = preferences.position === "top" ? "9%" : "auto";
      host.style.bottom = preferences.position === "top" ? "auto" : "9%";
      host.style.transform = "translateX(-50%)";
    }
  }

  function renderCaptions() {
    const rows = (entries) => entries.map((caption) => {
      const row = document.createElement("div"); row.className = "caption";
      if (caption.speaker) {
        const badge = document.createElement("span"); badge.className = "speaker";
        badge.textContent = caption.speaker;
        row.append(badge);
      }
      const source = document.createElement("div"); source.className = "line original";
      const original = caption.original || "";
      const matched = !caption.final && caption.stablePrefix && original.startsWith(caption.stablePrefix)
        ? caption.stablePrefix : "";
      if (matched) {
        const prefix = document.createElement("span"); prefix.textContent = matched;
        const tentative = document.createElement("span"); tentative.className = "tentative";
        tentative.textContent = original.slice(matched.length);
        source.append(prefix, tentative);
      } else source.textContent = original;
      source.hidden = !preferences.showOriginal || !original;
      const target = document.createElement("div"); target.className = "line translation";
      target.textContent = caption.translation || "";
      if (!caption.final) target.className += " tentative";
      target.hidden = !preferences.showTranslation || !target.textContent;
      row.hidden = source.hidden && target.hidden;
      row.append(source, target);
      return row;
    });
    captionList.replaceChildren(...rows(captions.slice(-Math.max(1, Math.min(3, Number(preferences.visibleCaptions) || 2)))));
    historyList.replaceChildren(...rows(history));
    historyButton.hidden = history.length === 0;
  }

  function clear(nextEpoch) {
    epoch = nextEpoch;
    ensureOverlay();
    captions = [];
    history = [];
    renderCaptions();
    activeUtterance = -1;
    activeCueKeys.clear();
    prefetchedCueKeys.clear();
    historyPanel.hidden = true;
    historyButton.textContent = "History · pause to read";
    status.hidden = true;
  }

  function applyPreferences() {
    if (!installation.active) return;
    try {
      chrome.storage.local.get(preferences).then((prefs) => {
        if (!installation.active) return;
        ensureOverlay();
        preferences = prefs;
        sourceSelect.value = prefs.sourceLanguage || "auto";
        targetSelect.value = prefs.targetLanguage || "zh";
        renderCaptions();
        host.style.setProperty("--vat-size", `${Math.max(14, Math.min(48, Number(prefs.fontSize)))}px`);
        positionOverlay();
      }).catch(handleExtensionError);
    } catch (error) { handleExtensionError(error); }
  }

  function trackVideo() {
    const video = activeVideo();
    if (!video || video === trackedVideo) return;
    trackedVideo = video;
    video.addEventListener("seeking", () => {
      sendToBackground({ target: "background", type: "vat:video-event", event: "seeking" });
    });
    for (const event of ["pause", "playing", "ended"]) {
      video.addEventListener(event, () => sendToBackground({
        target: "background", type: "vat:video-event", event,
      }));
    }
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "vat:probe-track") {
      sendResponse({ available: !!availableTrack() });
      return;
    }
    if (message.type === "vat:track-start") {
      stopTrack();
      selectedTrack = availableTrack();
      if (selectedTrack) {
        selectedTrackMode = selectedTrack.mode;
        if (selectedTrack.mode === "showing") selectedTrack.mode = "hidden";
        selectedTrack.addEventListener("cuechange", onCueChange);
        onCueChange();
      }
      sendResponse({ active: !!selectedTrack });
      return;
    }
    if (message.type === "vat:track-stop") { stopTrack(); return; }
    if (message.type === "vat:hide") {
      epoch++;
      captions = [];
      history = [];
      activeUtterance = -1;
      host?.remove();
      host = null;
      return;
    }
    if (message.type === "vat:track-refresh") { onCueChange(); return; }
    if (message.type === "vat:clear") { clear(message.epoch); return; }
    if (message.type === "vat:hold") { epoch = message.epoch; activeUtterance = -1; return; }
    if (message.type === "vat:subtitle") {
      if (message.epoch !== epoch) return;
      const key = `${message.epoch}:${message.utterance_id}`;
      const older = message.utterance_id < activeUtterance;
      if (older && !captions.some((item) => item.utteranceId === message.utterance_id)
          && !history.some((item) => item.key === key)) return;
      if (!older) activeUtterance = message.utterance_id;
      ensureOverlay();
      const caption = { utteranceId: message.utterance_id,
        original: message.original || "", translation: message.translation || "", speaker: message.speaker,
        stablePrefix: message.stable_prefix || "", final: !!message.final };
      const index = captions.findIndex((item) => item.utteranceId === caption.utteranceId);
      if (index >= 0) captions[index] = caption;
      else if (!older) captions.push(caption);
      captions = captions.slice(-maxVisibleCaptions);
      if (message.final) {
        const past = history.findIndex((item) => item.key === key);
        if (past >= 0) history[past] = { ...caption, key };
        else if (!older) history.push({ ...caption, key });
        history = history.slice(-100);
      }
      renderCaptions();
      status.hidden = true;
    }
    if (message.type === "vat:status") {
      ensureOverlay(); status.textContent = message.message || message.state || ""; status.hidden = !status.textContent;
    }
    if (message.type === "vat:error") {
      ensureOverlay(); status.textContent = message.message || "Translation service error."; status.hidden = false;
    }
  });

  chrome.storage.onChanged.addListener((_, area) => { if (area === "local") applyPreferences(); });
  observer = new MutationObserver(trackVideo);
  observer.observe(document.documentElement, { childList: true, subtree: true });
  document.addEventListener("fullscreenchange", () => {
    if (host) {
      const fullscreen = document.fullscreenElement;
      (fullscreen && fullscreen.tagName !== "VIDEO" ? fullscreen : document.documentElement).append(host);
    }
    trackVideo();
  });
  applyPreferences();
  trackVideo();
})();
