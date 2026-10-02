let stream = null;
let audioContext = null;
let socket = null;
let epoch = 0;
let sequence = 0;
let sending = true;
let sessionId = null;
let generation = 0;
let lastBackpressureAt = 0;
let sourceLanguage = "auto";
let targetLanguage = "zh";

function status(state, message = "") {
  chrome.runtime.sendMessage({ target: "background", type: "status", state, message, epoch });
}

function sendControl(payload) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(payload));
}

function closeResources() {
  const previousSocket = socket;
  socket = null;
  previousSocket?.close();
  stream?.getTracks().forEach((track) => track.stop()); stream = null;
  audioContext?.close(); audioContext = null;
}

function fail(message, id) {
  if (id !== sessionId) return;
  sessionId = null;
  generation++;
  closeResources();
  chrome.runtime.sendMessage({ target: "background", type: "vat:ended", session_id: id, message });
}

async function start({ streamId, session, token }) {
  const run = ++generation;
  sessionId = session.id;
  closeResources();
  epoch = session.epoch;
  sourceLanguage = session.sourceLanguage || "auto";
  targetLanguage = session.targetLanguage || "zh";
  sequence = 0;
  sending = true;
  lastBackpressureAt = 0;
  try {
    const capturedStream = await navigator.mediaDevices.getUserMedia({
      audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
      video: false,
    });
    if (run !== generation) {
      capturedStream.getTracks().forEach((track) => track.stop());
      return;
    }
    stream = capturedStream;
    audioContext = new AudioContext();
    await audioContext.resume();
    await audioContext.audioWorklet.addModule("audio-worklet.js");
    if (run !== generation) return;
    const source = audioContext.createMediaStreamSource(stream);
    // tabCapture silences the source tab unless this explicit replay edge exists.
    source.connect(audioContext.destination);
    const processor = new AudioWorkletNode(audioContext, "vat-pcm16");
    source.connect(processor);
    const silentSink = audioContext.createGain();
    silentSink.gain.value = 0;
    processor.port.onmessage = ({ data }) => {
      if (run !== generation || !sending || socket?.readyState !== WebSocket.OPEN) return;
      if (socket.bufferedAmount > 1_000_000) {
        if (Date.now() - lastBackpressureAt > 5000) {
          lastBackpressureAt = Date.now();
          status("backpressure", "Local processing is falling behind; some audio may be missed. Try enabling the site's captions.");
        }
        return;
      }
      const header = new ArrayBuffer(8);
      const view = new DataView(header);
      view.setUint32(0, epoch, true);
      view.setUint32(4, sequence++, true);
      const packet = new Uint8Array(8 + data.byteLength);
      packet.set(new Uint8Array(header));
      packet.set(new Uint8Array(data), 8);
      socket.send(packet);
    };
    // Keep the worklet in the pull graph without mixing captured audio twice.
    processor.connect(silentSink).connect(audioContext.destination);
    const currentSocket = new WebSocket("ws://127.0.0.1:8765/ws", ["vat", `token.${token}`]);
    socket = currentSocket;
    currentSocket.onopen = () => {
      if (socket !== currentSocket || sessionId !== session.id) return;
      sendControl({ type: "start", session_id: session.id, epoch, mode: session.mode,
        audio_mode: session.audioMode, source_language: sourceLanguage,
        target_language: targetLanguage,
        term_pack_enabled: session.termPackEnabled,
        glossary: session.glossary || "" });
      status("capturing");
    };
    currentSocket.onmessage = ({ data }) => {
      if (socket !== currentSocket || sessionId !== session.id) return;
      try {
        const event = JSON.parse(data);
        if (event.type === "error" && event.code !== "inference_failed") {
          fail(event.message || "Local inference failed.", session.id);
        } else if (event.type === "error") {
          status("recovering", `This segment failed; capture continues: ${event.message || "unknown error"}`);
        }
        else chrome.runtime.sendMessage({ target: "background", ...event });
      } catch { fail("The local service returned an invalid message.", session.id); }
    };
    currentSocket.onerror = () => {
      if (socket === currentSocket) fail("Cannot connect to the local service. Check that it is running.", session.id);
    };
    currentSocket.onclose = (event) => {
      if (socket === currentSocket) fail(event.code === 1008 ? "Invalid local service token." : "Local service connection closed.", session.id);
    };
    stream.getAudioTracks()[0]?.addEventListener("ended", () => {
      if (socket === currentSocket) fail("Tab audio capture ended.", session.id);
    });
  } catch (error) {
    fail(error.message, session.id);
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.target !== "offscreen") return;
  if (message.type === "vat:start") void start(message);
  if (message.type === "vat:reset") { epoch = message.epoch; sequence = 0; sending = !message.paused; sendControl({ type: "reset", epoch }); }
  if (message.type === "vat:pause") { sending = false; sendControl({ type: "pause" }); }
  if (message.type === "vat:configure") {
    epoch = message.epoch; sequence = 0;
    sourceLanguage = message.sourceLanguage; targetLanguage = message.targetLanguage;
    sendControl({ type: "configure", epoch, source_language: sourceLanguage, target_language: targetLanguage });
  }
  if (message.type === "vat:playing") sending = true;
  if (message.type === "vat:stop") { sessionId = null; generation++; sendControl({ type: "stop" }); closeResources(); status("stopped"); }
});
