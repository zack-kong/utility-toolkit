const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const extension = path.resolve(__dirname, '..', 'extension');

test('background forwards the content-script subtitle event and drops stale epochs', async () => {
  let onMessage;
  const forwarded = [];
  const chrome = {
    storage: { session: { get: async () => ({ activeSession: { tabId: 7, epoch: 2 } }) } },
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } } },
    action: { onClicked: { addListener: () => {} } },
    tabs: {
      onRemoved: { addListener: () => {} },
      sendMessage: async (tabId, message) => forwarded.push({ tabId, message }),
    },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome });
  onMessage({ target: 'background', type: 'subtitle', epoch: 2, original: 'hello' }, {});
  await new Promise(setImmediate);
  assert.equal(forwarded[0].tabId, 7);
  assert.equal(forwarded[0].message.type, 'vat:subtitle');
  onMessage({ target: 'background', type: 'subtitle', epoch: 1, original: 'stale' }, {});
  await new Promise(setImmediate);
  assert.equal(forwarded.length, 1);
});

test('old capture ended event does not clear a new session', async () => {
  let onMessage;
  let removed = false;
  const chrome = {
    storage: { session: {
      get: async () => ({ activeSession: { id: 'new', tabId: 7, epoch: 0 } }),
      remove: async () => { removed = true; },
    } },
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } } },
    action: { onClicked: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} }, sendMessage: async () => {} },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome });
  onMessage({ target: 'background', type: 'vat:ended', session_id: 'old', message: 'closed' }, {});
  await new Promise(setImmediate);
  assert.equal(removed, false);
});

test('active capture disconnect clears stale captions before showing error', async () => {
  let onMessage;
  let removed = false;
  const delivered = [];
  const chrome = {
    storage: { session: {
      get: async () => ({ activeSession: { id: 'active', tabId: 7, epoch: 3 } }),
      remove: async () => { removed = true; },
    } },
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } } },
    action: { onClicked: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} },
      sendMessage: async (_, message) => delivered.push(message) },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome });
  onMessage({ target: 'background', type: 'vat:ended', session_id: 'active', message: '连接已断开' }, {});
  await new Promise(setImmediate);
  assert.deepEqual(delivered.map((message) => message.type), ['vat:clear', 'vat:error']);
  assert.equal(delivered[0].epoch, 4);
  assert.equal(removed, true);
});

test('action starts registered native service before tab capture', async () => {
  let onClicked;
  const calls = [];
  const chrome = {
    storage: {
      session: { get: async () => ({}), set: async () => {} },
      local: {
        get: async () => ({ token: '', mode: 'accurate', audioMode: 'dialogue' }),
        set: async (value) => calls.push(['token', value.token]),
      },
    },
    runtime: {
      getContexts: async () => [{ contextType: 'OFFSCREEN_DOCUMENT' }],
      sendNativeMessage: async (host, message) => {
        calls.push(['native', host, message.command]);
        return { ok: true, token: 'local-test-token' };
      },
      sendMessage: async (message) => calls.push(['offscreen', message.type, message.token]),
      onMessage: { addListener: () => {} },
    },
    scripting: { executeScript: async () => {} },
    tabCapture: { getMediaStreamId: async () => { calls.push(['capture']); return 'stream'; } },
    tabs: { sendMessage: async () => {}, onRemoved: { addListener: () => {} } },
    action: { onClicked: { addListener: (callback) => { onClicked = callback; } } },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), {
    chrome, crypto: { randomUUID: () => 'session' },
  });
  await onClicked({ id: 7 });
  assert.deepEqual(calls[0], ['native', 'com.video_auto_translate.host', 'ensure_running']);
  assert.deepEqual(calls[1], ['token', 'local-test-token']);
  assert.deepEqual(calls[2], ['capture']);
  assert.deepEqual(calls.at(-1), ['offscreen', 'vat:start', 'local-test-token']);
});

test('pausing keeps captions available for reading, seeking clears them', async () => {
  let onMessage;
  let session = { tabId: 7, epoch: 0 };
  const delivered = [];
  const chrome = {
    storage: { session: {
      get: async () => ({ activeSession: session }),
      set: async (value) => { session = value.activeSession; },
    } },
    runtime: {
      onMessage: { addListener: (callback) => { onMessage = callback; } },
      sendMessage: async (message) => delivered.push(message),
    },
    action: { onClicked: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} }, sendMessage: async (_, message) => delivered.push(message) },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome });
  onMessage({ target: 'background', type: 'vat:video-event', event: 'pause' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.equal(session.epoch, 0);
  assert.ok(delivered.some((message) => message.type === 'vat:pause'));
  assert.equal(delivered.at(-1).type, 'vat:hold');
  onMessage({ target: 'background', type: 'vat:video-event', event: 'seeking' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.equal(session.epoch, 1);
  assert.equal(delivered.at(-1).type, 'vat:clear');
});

test('language bar change reconfigures track session without restarting capture', async () => {
  let onMessage;
  let session = { id: 's', tabId: 7, epoch: 0, source: 'track', sourceLanguage: 'auto', targetLanguage: 'zh' };
  const delivered = [];
  const chrome = {
    storage: { session: {
      get: async () => ({ activeSession: session }),
      set: async (value) => { session = value.activeSession; },
    } },
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } } },
    action: { onClicked: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} },
      sendMessage: async (_, message) => delivered.push(message) },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome });
  onMessage({ target: 'background', type: 'vat:configure-language', sourceLanguage: 'ja',
    targetLanguage: 'en' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.equal(session.epoch, 1);
  assert.equal(session.sourceLanguage, 'ja');
  assert.equal(session.targetLanguage, 'en');
  assert.deepEqual(delivered.map((message) => message.type), ['vat:clear', 'vat:track-refresh']);
});

test('a stale offscreen close cannot end the replacement session', async () => {
  let onMessage;
  const sent = [];
  const sockets = [];
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.bufferedAmount = 0; sockets.push(this); }
    send() {}
    close() { this.readyState = 3; }
  }
  class AudioContext {
    constructor() { this.destination = {}; this.audioWorklet = { addModule: async () => {} }; }
    async resume() {}
    async close() {}
    createMediaStreamSource() { return { connect() {} }; }
    createGain() { return { gain: { value: 1 }, connect() { return this; } }; }
  }
  class AudioWorkletNode { constructor() { this.port = {}; } connect(sink) { return sink; } }
  const chrome = { runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } },
    sendMessage: (message) => sent.push(message) } };
  const navigator = { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }],
    getAudioTracks: () => [{ addEventListener() {} }] }) } };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'offscreen.js'), 'utf8'), {
    chrome, navigator, AudioContext, AudioWorkletNode, WebSocket: Socket,
    ArrayBuffer, DataView, Uint8Array, JSON,
  });
  onMessage({ target: 'offscreen', type: 'vat:start', streamId: 'old', session: { id: 'old', epoch: 0 }, token: 'x' });
  await new Promise(setImmediate);
  onMessage({ target: 'offscreen', type: 'vat:start', streamId: 'new', session: { id: 'new', epoch: 0 }, token: 'x' });
  await new Promise(setImmediate);
  sockets[0].onclose({ code: 1006 });
  assert.equal(sockets[1].readyState, 1);
  assert.equal(sent.filter((message) => message.type === 'vat:ended').length, 0);
  sockets[0].onerror();
  assert.equal(sockets[1].readyState, 1);
});

test('one inference failure does not stop audio capture', async () => {
  let onMessage;
  const sent = [];
  const sockets = [];
  class Socket {
    static OPEN = 1;
    constructor() { this.readyState = 1; this.bufferedAmount = 0; sockets.push(this); }
    send(data) { this.sent ??= []; this.sent.push(data); }
    close() { this.readyState = 3; }
  }
  class AudioContext {
    constructor() { this.destination = {}; this.audioWorklet = { addModule: async () => {} }; }
    async resume() {}
    async close() {}
    createMediaStreamSource() { return { connect() {} }; }
    createGain() { return { gain: { value: 1 }, connect() { return this; } }; }
  }
  class AudioWorkletNode { constructor() { this.port = {}; } connect(sink) { return sink; } }
  const chrome = { runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } },
    sendMessage: (message) => sent.push(message) } };
  const navigator = { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }],
    getAudioTracks: () => [{ addEventListener() {} }] }) } };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'offscreen.js'), 'utf8'), {
    chrome, navigator, AudioContext, AudioWorkletNode, WebSocket: Socket,
    ArrayBuffer, DataView, Uint8Array, JSON,
  });
  onMessage({ target: 'offscreen', type: 'vat:start', streamId: 'stream',
    session: { id: 'active', epoch: 0, sourceLanguage: 'ja', targetLanguage: 'en' }, token: 'x' });
  await new Promise(setImmediate);
  sockets[0].onopen();
  assert.equal(JSON.parse(sockets[0].sent[0]).target_language, 'en');
  onMessage({ target: 'offscreen', type: 'vat:configure', epoch: 1,
    sourceLanguage: 'ko', targetLanguage: 'es' });
  assert.equal(JSON.parse(sockets[0].sent.at(-1)).target_language, 'es');
  onMessage({ target: 'offscreen', type: 'vat:pause' });
  assert.equal(JSON.parse(sockets[0].sent.at(-1)).type, 'pause');
  onMessage({ target: 'offscreen', type: 'vat:playing' });
  sockets[0].onmessage({ data: JSON.stringify({ type: 'error', code: 'inference_failed', message: 'retry' }) });
  assert.equal(sockets[0].readyState, 1);
  assert.equal(sent.at(-1).state, 'recovering');
  assert.equal(sent.filter((message) => message.type === 'vat:ended').length, 0);
});

test('active HTML5 captions use local text translation without tab capture', async () => {
  let onClicked;
  let onMessage;
  let session = null;
  let captured = false;
  const delivered = [];
  const requests = [];
  const chrome = {
    storage: {
      session: {
        get: async () => session ? { activeSession: session } : {},
        set: async (value) => { session = value.activeSession; },
      },
      local: { get: async () => ({ token: 'local-token', mode: 'accurate', audioMode: 'dialogue',
        glossary: 'ja|ドナルド = 唐老鸭' }), set: async () => {} },
    },
    runtime: {
      sendNativeMessage: async () => ({ ok: true, token: 'local-token' }),
      onMessage: { addListener: (callback) => { onMessage = callback; } },
    },
    scripting: { executeScript: async () => {} },
    tabCapture: { getMediaStreamId: async () => { captured = true; return 'stream'; } },
    tabs: {
      onRemoved: { addListener: () => {} },
      sendMessage: async (_, message) => {
        if (message.type === 'vat:probe-track') return { available: true };
        if (message.type === 'vat:track-start') return { active: true };
        delivered.push(message);
      },
    },
    action: { onClicked: { addListener: (callback) => { onClicked = callback; } } },
  };
  const fetch = async (_, options) => {
    requests.push(JSON.parse(options.body));
    return { ok: true, json: async () => ({ translation: '你好' }) };
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), {
    chrome, fetch, crypto: { randomUUID: () => 'session' },
  });
  await onClicked({ id: 7 });
  assert.equal(session.source, 'track');
  assert.equal(captured, false);
  onMessage({ target: 'background', type: 'vat:cue', epoch: 0, utterance_id: 1,
    original: 'Hello', language: 'en', speaker: 'A' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.deepEqual(delivered.filter((event) => event.type === 'vat:subtitle').map((event) => event.translation), ['', '你好']);
  assert.equal(delivered.find((event) => event.type === 'vat:subtitle').speaker, 'A');
  assert.equal(requests[0].glossary, 'ja|ドナルド = 唐老鸭');
});

test('prefetched track cue is reused when it becomes active', async () => {
  let onMessage;
  let fetchCount = 0;
  const delivered = [];
  const session = { id: 's', tabId: 7, epoch: 0, source: 'track' };
  const chrome = {
    storage: { session: { get: async () => ({ activeSession: session }) },
      local: { get: async () => ({ token: 'test' }) } },
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } } },
    action: { onClicked: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} }, sendMessage: async (_, message) => delivered.push(message) },
  };
  const fetch = async () => { fetchCount++; return { ok: true, json: async () => ({ translation: '你好' }) }; };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome, fetch });
  onMessage({ target: 'background', type: 'vat:prefetch-cue', epoch: 0,
    original: 'Hello', language: 'en' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  onMessage({ target: 'background', type: 'vat:cue', epoch: 0, utterance_id: 1,
    original: 'Hello', language: 'en' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.equal(fetchCount, 1);
  assert.equal(delivered.at(-1).translation, '你好');
});

test('audio worklet mixes stereo and produces 16 kHz PCM blocks', () => {
  let Processor;
  const blocks = [];
  class BaseProcessor { constructor() { this.port = { postMessage: (data) => blocks.push(data) }; } }
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'audio-worklet.js'), 'utf8'), {
    AudioWorkletProcessor: BaseProcessor,
    sampleRate: 48000,
    registerProcessor: (_, implementation) => { Processor = implementation; },
    Int16Array,
  });
  const processor = new Processor();
  const left = new Float32Array(480).fill(1);
  const right = new Float32Array(480).fill(-1);
  processor.process([[left, right]]);
  processor.process([[left, right]]);
  assert.equal(blocks.length, 1);
  assert.equal(new Int16Array(blocks[0]).length, 320);
  assert.equal(new Int16Array(blocks[0])[0], 0);
});

test('content overlay retains three recent utterances and clears on epoch change', async () => {
  let onMessage;
  class Element {
    constructor() { this.children = []; this.listeners = {}; this.style = { setProperty: () => {} }; this.isConnected = true; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    attachShadow() { this.shadow = new Element(); return this.shadow; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    getBoundingClientRect() { return { left: 140, top: 500, width: 1000, height: 100 }; }
    setPointerCapture(id) { this.capturedPointer = id; }
    hasPointerCapture(id) { return this.capturedPointer === id; }
    releasePointerCapture() { this.capturedPointer = null; }
    remove() { this.isConnected = false; }
  }
  const root = new Element();
  let pauseCount = 0;
  const video = { clientWidth: 640, clientHeight: 360, addEventListener: () => {}, pause: () => { pauseCount++; } };
  const document = {
    documentElement: root,
    fullscreenElement: null,
    createElement: () => new Element(),
    querySelectorAll: () => [video],
    addEventListener: () => {},
  };
  const window = { innerWidth: 1280, innerHeight: 720 }; window.top = window;
  const stored = [];
  const sent = [];
  const chrome = {
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } },
      sendMessage: (message) => sent.push(message) },
    storage: { local: { get: async (defaults) => defaults, set: async (value) => stored.push(value) }, onChanged: { addListener: () => {} } },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'content.js'), 'utf8'), {
    chrome, document, window, MutationObserver: class { observe() {} },
  });
  await new Promise(setImmediate);
  const captionList = root.children[0].shadow.children[1];
  const tools = root.children[0].shadow.children[2];
  const historyButton = tools.children[3];
  const historyPanel = root.children[0].shadow.children[3];
  for (let utterance_id = 0; utterance_id < 4; utterance_id++) {
    onMessage({ type: 'vat:subtitle', epoch: 0, utterance_id, original: `line ${utterance_id}`, translation: `译文 ${utterance_id}`, final: true });
  }
  assert.deepEqual(captionList.children.map((row) => row.children[0].textContent), ['line 2', 'line 3']);
  assert.equal(historyPanel.children[0].children.length, 4);
  onMessage({ type: 'vat:subtitle', epoch: 0, utterance_id: 1, original: 'line 1', translation: '补全译文', final: true });
  assert.equal(historyPanel.children[0].children[1].children[1].textContent, '补全译文');
  assert.equal(captionList.children[1].children[0].textContent, 'line 3');
  onMessage({ type: 'vat:subtitle', epoch: 0, utterance_id: 3, original: 'corrected', translation: '修订', final: true });
  assert.equal(captionList.children.length, 2);
  assert.equal(historyPanel.children[0].children.length, 4);
  assert.equal(captionList.children[1].children[0].textContent, 'corrected');
  tools.children[0].listeners.pointerdown({ preventDefault() {}, pointerId: 1, clientX: 640, clientY: 550 });
  tools.children[0].listeners.pointermove({ pointerId: 1, clientX: 300, clientY: 300 });
  tools.children[0].listeners.pointerup({ pointerId: 1 });
  assert.equal(stored.at(-1).position, 'custom');
  tools.children[2].listeners.click();
  assert.equal(stored.at(-1).fontSize, 27);
  historyButton.listeners.click();
  assert.equal(pauseCount, 1);
  assert.equal(historyPanel.hidden, false);
  onMessage({ type: 'vat:hold', epoch: 1 });
  assert.equal(historyPanel.children[0].children.length, 4);
  onMessage({ type: 'vat:subtitle', epoch: 1, utterance_id: 4, original: 'new line', translation: '新字幕' });
  assert.equal(captionList.children.length, 2);
  assert.equal(captionList.children[1].children[0].textContent, 'new line');
  onMessage({ type: 'vat:subtitle', epoch: 1, utterance_id: 5, original: 'speaker line', translation: '说话人', speaker: 'A', final: true });
  assert.equal(captionList.children[1].children[0].textContent, 'A');
  assert.equal(captionList.children[1].children[1].textContent, 'speaker line');
  onMessage({ type: 'vat:clear', epoch: 2 });
  assert.equal(captionList.children.length, 0);
  assert.equal(historyPanel.children[0].children.length, 0);
  onMessage({ type: 'vat:subtitle', epoch: 1, utterance_id: 4, original: 'stale' });
  assert.equal(captionList.children.length, 0);
  onMessage({ type: 'vat:subtitle', epoch: 2, utterance_id: 6, original: 'なんだよ知らねえ',
    translation: '怎么回事', stable_prefix: 'なんだよ', final: false });
  const source = captionList.children[0].children[0];
  assert.equal(source.children[0].textContent, 'なんだよ');
  assert.equal(source.children[1].textContent, '知らねえ');
  assert.match(source.children[1].className, /tentative/);
  const languageBar = tools.children[4];
  languageBar.children[0].value = 'ja';
  languageBar.children[1].value = 'en';
  languageBar.children[1].listeners.change();
  assert.equal(stored.at(-1).targetLanguage, 'en');
  assert.equal(sent.at(-1).type, 'vat:configure-language');
  const closeButton = tools.children[5];
  closeButton.listeners.click();
  assert.equal(sent.at(-1).type, 'vat:stop-request');
  onMessage({ type: 'vat:hide' });
  assert.equal(root.children[0].isConnected, false);
});

test('close request stops only the matching tab session', async () => {
  let onMessage;
  let session = { tabId: 7, source: 'track', epoch: 2 };
  const delivered = [];
  const chrome = {
    storage: { session: { get: async () => ({ activeSession: session }),
      remove: async () => { session = null; } } },
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } } },
    action: { onClicked: { addListener: () => {} } },
    tabs: { onRemoved: { addListener: () => {} },
      sendMessage: async (tabId, message) => delivered.push({ tabId, type: message.type }) },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'background.js'), 'utf8'), { chrome });
  onMessage({ target: 'background', type: 'vat:stop-request' }, { tab: { id: 8 } });
  await new Promise(setImmediate);
  assert.equal(session.tabId, 7);
  onMessage({ target: 'background', type: 'vat:stop-request' }, { tab: { id: 7 } });
  await new Promise(setImmediate);
  assert.equal(session, null);
  assert.deepEqual(delivered.map((item) => item.type), ['vat:track-stop', 'vat:hide']);
  onMessage({ target: 'background', type: 'status', state: 'stopped', epoch: 2 }, {});
  await new Promise(setImmediate);
  assert.deepEqual(delivered.map((item) => item.type), ['vat:track-stop', 'vat:hide']);
});

test('invalidated content context stops event handlers without uncaught errors', async () => {
  const listeners = {};
  let disconnected = false;
  let removed = false;
  class Element {
    constructor() { this.children = []; this.style = { setProperty() {} }; this.isConnected = true; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    attachShadow() { return new Element(); }
    addEventListener() {}
    remove() { removed = true; }
  }
  const root = new Element();
  const video = { clientWidth: 640, clientHeight: 360,
    addEventListener: (name, callback) => { listeners[name] = callback; } };
  const document = { documentElement: root, fullscreenElement: null,
    createElement: () => new Element(), querySelectorAll: () => [video], addEventListener() {} };
  const window = {}; window.top = window;
  const chrome = {
    runtime: { onMessage: { addListener() {} }, sendMessage: () => {
      throw new Error('Extension context invalidated.');
    } },
    storage: { local: { get: async (defaults) => defaults }, onChanged: { addListener() {} } },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'content.js'), 'utf8'), {
    chrome, document, window, MutationObserver: class {
      observe() {}
      disconnect() { disconnected = true; }
    },
  });
  await new Promise(setImmediate);
  assert.doesNotThrow(() => listeners.seeking());
  assert.equal(disconnected, true);
  assert.equal(removed, true);
  assert.doesNotThrow(() => listeners.playing());
});

test('content script detects active text tracks and deduplicates cue changes', async () => {
  let onMessage;
  const sent = [];
  const track = {
    kind: 'subtitles', mode: 'showing', language: 'en', activeCues: [], cues: [],
    addEventListener(name, callback) { this.listener = callback; },
    removeEventListener() { this.listener = null; },
  };
  class Element {
    constructor() { this.children = []; this.style = { setProperty: () => {} }; this.isConnected = true; }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this.children = children; }
    attachShadow() { return new Element(); }
    addEventListener() {}
  }
  const root = new Element();
  const video = { clientWidth: 640, clientHeight: 360, currentTime: 1,
    textTracks: [track], addEventListener() {} };
  const document = { documentElement: root, fullscreenElement: null,
    createElement: () => new Element(), querySelectorAll: () => [video], addEventListener() {} };
  const window = {}; window.top = window;
  const chrome = {
    runtime: { onMessage: { addListener: (callback) => { onMessage = callback; } },
      sendMessage: (message) => sent.push(message) },
    storage: { local: { get: async (defaults) => defaults }, onChanged: { addListener: () => {} } },
  };
  vm.runInNewContext(fs.readFileSync(path.join(extension, 'content.js'), 'utf8'), {
    chrome, document, window, MutationObserver: class { observe() {} },
  });
  await new Promise(setImmediate);
  let response;
  onMessage({ type: 'vat:probe-track' }, {}, (value) => { response = value; });
  assert.equal(response.available, true);
  onMessage({ type: 'vat:track-start' }, {}, (value) => { response = value; });
  assert.equal(response.active, true);
  assert.equal(track.mode, 'hidden');
  track.activeCues = [{ startTime: 1, endTime: 2, text: '<v A>Hello</v>' }];
  track.cues = [...track.activeCues, { startTime: 3, endTime: 4, text: 'Future' }];
  track.listener(); track.listener();
  assert.equal(sent.filter((message) => message.type === 'vat:cue').length, 1);
  assert.equal(sent.filter((message) => message.type === 'vat:prefetch-cue').length, 1);
  assert.equal(sent.find((message) => message.type === 'vat:cue').original, 'Hello');
  assert.equal(sent.find((message) => message.type === 'vat:cue').speaker, 'A');
  onMessage({ type: 'vat:clear', epoch: 1 });
  onMessage({ type: 'vat:track-refresh' });
  assert.equal(sent.filter((message) => message.type === 'vat:cue').length, 2);
  assert.equal(sent.filter((message) => message.type === 'vat:cue').at(-1).epoch, 1);
  onMessage({ type: 'vat:track-stop' });
  assert.equal(track.mode, 'showing');
});
