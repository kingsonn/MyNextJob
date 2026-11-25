const said = document.getElementById("said");
const thread = document.getElementById("thread");
const steps = document.getElementById("steps");
const state = document.getElementById("state");
const hangup = document.getElementById("hangup");
const vadlog = document.getElementById("vadlog");
const history = [];

const SPEECH_RMS = 0.02;
const PLAYBACK_RMS = 0.08;
const SILENCE_MS = 700;
const MIN_SPEECH_MS = 300;

let onCall = false;
let opening = false;
let injected = false;
let playing = 0;
let vadState = "IDLE";
let stream = null;
let audioCtx = null;
let graph = [];
let utterance = [];
let speechMs = 0;
let silenceMs = 0;
let workletFrames = 0;
let healthTimer = 0;

function stamp() {
  return new Date().toISOString();
}

function log(text) {
  const line = stamp() + " " + text;
  console.log(line);
  if (!vadlog) {
    return;
  }
  vadlog.textContent = (vadlog.textContent + line + "\n").split("\n").slice(-24).join("\n");
}

function setVad(next) {
  vadState = next;
  log("VAD " + next);
  if (onCall && stream) {
    state.textContent = "On call. " + next + ".";
  }
}

function trackLine() {
  const track = stream && stream.getAudioTracks()[0];
  if (!track) {
    return "track missing";
  }
  return "track readyState=" + track.readyState + " enabled=" + track.enabled + " stream=" + stream.id;
}

function bubble(kind, text) {
  const item = document.createElement("div");
  item.className = "bubble " + kind;
  item.textContent = text;
  thread.appendChild(item);
  item.scrollIntoView({block: "nearest"});
}

function step(text) {
  const item = document.createElement("li");
  item.textContent = text;
  steps.appendChild(item);
}

function say(text) {
  if (!onCall || !window.speechSynthesis) {
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.onstart = () => {
    playing += 1;
    log("AI playback start");
  };
  utterance.onend = () => {
    playing = Math.max(0, playing - 1);
    log("AI playback complete");
  };
  utterance.onerror = () => {
    playing = Math.max(0, playing - 1);
    log("AI playback complete");
  };
  window.speechSynthesis.speak(utterance);
}

function rmsOf(samples) {
  let sum = 0;
  for (let index = 0; index < samples.length; index += 1) {
    sum += samples[index] * samples[index];
  }
  return Math.sqrt(sum / samples.length);
}

function onLevel(rms, dt, samples) {
  if (!onCall) {
    return;
  }
  const hot = rms >= (playing > 0 ? PLAYBACK_RMS : SPEECH_RMS);
  if (vadState === "IDLE") {
    if (!hot) {
      return;
    }
    utterance = [samples.slice(0)];
    speechMs = dt;
    silenceMs = 0;
    setVad("SPEECH_DETECTED");
    log("speech start");
    setVad("SPEECH_ACTIVE");
    return;
  }
  if (vadState !== "SPEECH_ACTIVE") {
    return;
  }
  utterance.push(samples.slice(0));
  if (hot) {
    speechMs += dt;
    silenceMs = 0;
    return;
  }
  silenceMs += dt;
  if (silenceMs < SILENCE_MS || speechMs < MIN_SPEECH_MS) {
    return;
  }
  const taken = utterance;
  utterance = [];
  speechMs = 0;
  silenceMs = 0;
  setVad("ENDPOINT_DETECTED");
  log("speech end");
  setVad("PROCESSING");
  log("utterance submission");
  setVad("IDLE");
  log("VAD idle " + trackLine());
  sendAudio(taken);
}

function takePcm(samples) {
  workletFrames += 1;
  if (injected || !audioCtx) {
    return;
  }
  const dt = (samples.length / audioCtx.sampleRate) * 1000;
  onLevel(rmsOf(samples), dt, samples);
}

function encodeWav(chunks, rate) {
  let length = 0;
  for (const chunk of chunks) {
    length += chunk.length;
  }
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const write = (offset, text) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  write(0, "RIFF");
  view.setUint32(4, 36 + length * 2, true);
  write(8, "WAVE");
  write(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, "data");
  view.setUint32(40, length * 2, true);
  let offset = 44;
  for (const chunk of chunks) {
    for (let index = 0; index < chunk.length; index += 1) {
      const sample = Math.max(-1, Math.min(1, chunk[index]));
      view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
      offset += 2;
    }
  }
  return new Uint8Array(buffer);
}

function toBase64(bytes) {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]);
  }
  return btoa(binary);
}

async function sendBody(payload, fromCall) {
  log("AI generation start");
  steps.replaceChildren();
  let saidText = payload.transcript || "";
  const response = await fetch("/voice/turn", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    bubble("agent", "The desk session is missing. Refresh this page.");
    log("AI generation complete");
    return;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let spoken = [];
  let endCall = false;
  while (true) {
    const chunk = await reader.read();
    if (chunk.done) {
      break;
    }
    buffer += decoder.decode(chunk.value, {stream: true});
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line) {
        continue;
      }
      const event = JSON.parse(line);
      if (event.type === "step") {
        step(event.text);
        if (event.text.indexOf("Heard: ") === 0) {
          saidText = event.text.slice("Heard: ".length);
          bubble("you", saidText);
        }
      }
      if (event.type === "done") {
        spoken = event.spoken;
        endCall = event.end_call === true;
        step("Answer from " + event.provider);
        for (const sentence of event.spoken) {
          bubble("agent", sentence);
          if (fromCall) {
            say(sentence);
          }
        }
      }
    }
  }
  history.push({role: "user", content: saidText || "(spoken)"});
  history.push({role: "assistant", content: spoken.join(" ")});
  log("AI generation complete");
  if (!fromCall) {
    said.value = "";
  }
  if (endCall) {
    stopCapture("agent ended the call");
  }
}

async function sendAudio(chunks) {
  const rate = audioCtx ? audioCtx.sampleRate : 48000;
  const wav = encodeWav(chunks, rate);
  await sendBody({audio_wav_base64: toBase64(wav), history: history.slice()}, true);
}

function releaseGraph() {
  for (const node of graph) {
    try {
      node.disconnect();
    } catch (error) {
      log("disconnect " + error);
    }
  }
  graph = [];
  if (stream) {
    for (const track of stream.getAudioTracks()) {
      track.stop();
    }
  }
  stream = null;
  if (audioCtx && audioCtx.state !== "closed") {
    audioCtx.close();
  }
  audioCtx = null;
}

function stopCapture(reason) {
  onCall = false;
  hangup.disabled = true;
  if (window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  log("capture stop " + reason);
  releaseGraph();
  state.textContent = reason + ". The thread stays. Type, or start again.";
}

async function attach(source) {
  const mute = audioCtx.createGain();
  mute.gain.value = 0;
  try {
    await audioCtx.audioWorklet.addModule("/voice/vad-worklet.js");
    const node = new AudioWorkletNode(audioCtx, "claimpilot-vad");
    node.port.onmessage = (event) => takePcm(event.data);
    source.connect(node);
    node.connect(mute);
    mute.connect(audioCtx.destination);
    graph.push(source, node, mute);
    log("AudioWorklet processing");
  } catch (error) {
    log("AudioWorklet unavailable " + error);
    const processor = audioCtx.createScriptProcessor(2048, 1, 1);
    processor.onaudioprocess = (event) => {
      takePcm(event.inputBuffer.getChannelData(0).slice(0));
    };
    source.connect(processor);
    processor.connect(mute);
    mute.connect(audioCtx.destination);
    graph.push(source, processor, mute);
    log("script processor active");
  }
}

async function openCapture(existing) {
  if (opening) {
    return;
  }
  opening = true;
  try {
    if (existing) {
      stream = existing;
    } else {
      log("microphone stream activation");
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {echoCancellation: true, noiseSuppression: true, autoGainControl: true},
      });
    }
    log(trackLine());
    audioCtx = new AudioContext();
    log("AudioContext " + audioCtx.state);
    if (audioCtx.state === "suspended") {
      await audioCtx.resume();
      log("AudioContext " + audioCtx.state);
    }
    const source = audioCtx.createMediaStreamSource(stream);
    await attach(source);
    setVad("IDLE");
    log("capture remains active");
  } finally {
    opening = false;
  }
}

async function recover(reason) {
  if (!onCall || opening) {
    return;
  }
  log("recovery " + reason);
  releaseGraph();
  try {
    await openCapture();
  } catch (error) {
    log("recovery failed " + error);
  }
}

document.getElementById("call").onclick = async () => {
  if (onCall && stream && audioCtx && audioCtx.state !== "closed") {
    return;
  }
  onCall = true;
  hangup.disabled = false;
  state.textContent = "On call. Opening the microphone.";
  try {
    await openCapture();
  } catch (error) {
    stopCapture("Microphone permission failed");
    log("microphone failed " + error);
  }
};

hangup.onclick = () => stopCapture("You ended the call");

document.getElementById("send").onclick = () => {
  const text = said.value.trim();
  if (!text) {
    return;
  }
  bubble("you", text);
  sendBody({transcript: text, history: history.slice()}, onCall);
};

said.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    document.getElementById("send").click();
  }
});

healthTimer = window.setInterval(() => {
  if (!onCall || opening || injected) {
    return;
  }
  const track = stream && stream.getAudioTracks()[0];
  if (!track || track.readyState !== "live" || !audioCtx || audioCtx.state === "closed") {
    recover("pipeline stopped");
    return;
  }
  if (audioCtx.state === "suspended") {
    log("AudioContext suspended");
    audioCtx.resume();
  }
}, 2000);

window.__claimpilot = {
  exercise: async (turns) => {
    injected = true;
    onCall = true;
    hangup.disabled = false;
    const ctx = new AudioContext();
    const dest = ctx.createMediaStreamDestination();
    const osc = ctx.createOscillator();
    const mute = ctx.createGain();
    mute.gain.value = 0;
    osc.connect(mute);
    mute.connect(dest);
    osc.start();
    await openCapture(dest.stream);
    const id = stream.id;
    const during = [];
    const original = window.fetch;
    window.fetch = async (url, options) => {
      if (String(url).indexOf("/voice/turn") !== -1) {
        during.push({
          vad: vadState,
          stream: stream && stream.id,
          track: trackLine(),
          ctx: audioCtx && audioCtx.state,
          worklet: workletFrames,
        });
        const body = JSON.stringify({
          type: "done",
          spoken: ["Noted."],
          provider: "scripted",
          events: ["fast"],
          end_call: false,
        }) + "\n";
        return new Response(body, {status: 200});
      }
      return original(url, options);
    };
    try {
      for (let turn = 0; turn < turns; turn += 1) {
        for (let frame = 0; frame < 20; frame += 1) {
          onLevel(0.08, 20, new Float32Array(160));
        }
        for (let frame = 0; frame < 40; frame += 1) {
          onLevel(0.001, 20, new Float32Array(160));
        }
        await new Promise((resolve) => setTimeout(resolve, 40));
        if (vadState !== "IDLE") {
          throw new Error("turn " + turn + " left VAD in " + vadState);
        }
        if (!stream || stream.id !== id) {
          throw new Error("stream was replaced");
        }
      }
      return {
        turns: turns,
        sameStream: stream.id === id,
        vad: vadState,
        track: trackLine(),
        ctx: audioCtx.state,
        worklet: workletFrames,
        during: during,
      };
    } finally {
      window.fetch = original;
      injected = false;
      osc.stop();
    }
  },
};
