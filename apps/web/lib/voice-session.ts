import type { Call } from "./api";

const terminal = new Set(["COMPLETED", "HANDOFF", "ENDED", "BLOCKED_DNC"]);

export function wavBlob(chunks: Float32Array[], rate: number): Blob {
  const size = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + size * 2);
  const view = new DataView(buffer);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, "RIFF"); view.setUint32(4, 36 + size * 2, true); text(8, "WAVE");
  text(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, size * 2, true);
  let offset = 44;
  for (const chunk of chunks) for (const sample of chunk) {
    const value = Math.max(-1, Math.min(1, sample));
    view.setInt16(offset, value * (value < 0 ? 32768 : 32767), true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

type Hooks = {
  status: (value: string) => void;
  level: (value: number) => void;
  error: (value: string) => void;
  recording: (audio: Blob | null) => void;
  closed: () => void;
  send: (id: string, audio: Blob, signal: AbortSignal) => Promise<{ call: Call; heard: boolean }>;
};

/** One microphone stream per call. No native SpeechRecognition service required. */
export class VoiceSession {
  private stream?: MediaStream;
  private context?: AudioContext;
  private source?: MediaStreamAudioSourceNode;
  private processor?: AudioWorkletNode;
  private disposed = false;
  private call?: Call;
  private busy = false;
  private speaking = false;
  private spokenKey = "";
  private speechSequence = 0;
  private speechTimer?: ReturnType<typeof setTimeout>;
  private deadline?: ReturnType<typeof setTimeout>;
  private captureWatchdog?: ReturnType<typeof setInterval>;
  private request = new AbortController();
  private lastFrame = 0;
  private quietUntil = 0;
  private turn: Float32Array[] = [];
  private preRoll: Float32Array[] = [];
  private speechSeconds = 0;
  private silenceSeconds = 0;
  private turnSeconds = 0;
  private recording: Float32Array[] = [];
  private discardRecording = false;
  muted = false;

  constructor(private hooks: Hooks) {}

  async open() {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      throw new Error("Microphone requires HTTPS or localhost. Open this dashboard in a full browser, not an embedded preview.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    if (this.disposed) { stream.getTracks().forEach((track) => track.stop()); return; }
    this.stream = stream;
    // #region debug-point B:persistent-capture
    void fetch("http://127.0.0.1:7777/event", { method: "POST", body: JSON.stringify({ sessionId: "voice-capture", runId: "post-fix", hypothesisId: "B", msg: "[DEBUG] persistent capture", data: { tracks: stream.getTracks().map((t) => t.readyState) } }) }).catch(() => {});
    // #endregion
    this.context = new AudioContext();
    await this.context.resume();
    await this.context.audioWorklet.addModule("/microphone-worklet.js");
    if (this.disposed) return;
    this.processor = new AudioWorkletNode(this.context, "microphone-capture");
    this.source = this.context.createMediaStreamSource(stream);
    this.source.connect(this.processor);
    this.processor.connect(this.context.destination); // Worklet outputs silence.
    this.processor.port.onmessage = (event: MessageEvent<Float32Array>) => this.capture(event.data);
    for (const track of stream.getAudioTracks()) {
      track.onended = () => this.fail("Microphone disconnected. Reconnect it and start voice recovery again.");
      track.onmute = () => this.hooks.status("Microphone interrupted");
    }
    this.context.onstatechange = () => {
      if (!this.disposed && this.context?.state === "suspended") {
        this.fail("Audio was suspended by the browser. Keep this tab in the foreground and restart voice recovery.");
      }
    };
    this.lastFrame = Date.now();
    this.captureWatchdog = setInterval(() => {
      if (Date.now() - this.lastFrame > 5000) this.fail("Microphone stopped delivering audio. Check device access and restart.");
    }, 2000);
    this.deadline = setTimeout(() => this.fail("Ten-minute local recording limit reached. Start a new call."), 600000);
  }

  update(call: Call) {
    if (this.disposed) return;
    if (this.call && this.call.call_id !== call.call_id) { this.close(false); return; }
    this.call = call;
    if (call.status === "HANDOFF") {
      this.discardRecording = true;
      this.recording = [];
    }
    const latest = [...call.transcript].reverse().find((turn) => turn.role === "agent");
    const key = latest ? `${latest.created_at}:${latest.text}` : "";
    if (latest && key !== this.spokenKey) {
      this.spokenKey = key;
      this.speak(latest.text);
    } else if (terminal.has(call.status) && !this.speaking) this.close(true);
  }

  private capture(samples: Float32Array) {
    if (this.disposed || !this.context) return;
    this.lastFrame = Date.now();
    const rate = this.context.sampleRate;
    const seconds = samples.length / rate;
    const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
    this.hooks.level(Math.min(1, rms * 8));
    if (this.call?.consent_given && !this.discardRecording && !terminal.has(this.call.status)) {
      this.recording.push(samples);
    }
    if (!this.call || terminal.has(this.call.status) || this.busy || this.speaking || Date.now() < this.quietUntil) {
      this.resetTurn();
      return;
    }
    this.preRoll.push(samples);
    if (this.preRoll.length > Math.ceil(rate * 0.3 / samples.length)) this.preRoll.shift();
    if (rms > 0.012) {
      if (!this.turn.length) this.turn.push(...this.preRoll.slice(0, -1));
      this.speechSeconds += seconds;
      this.silenceSeconds = 0;
    } else if (this.turn.length) this.silenceSeconds += seconds;
    if (!this.turn.length && rms <= 0.012) return;
    this.turn.push(samples);
    this.turnSeconds += seconds;
    if (this.turnSeconds > 29 || (this.silenceSeconds >= 0.9 && this.speechSeconds >= 0.15)) {
      const blob = wavBlob(this.turn, rate);
      this.resetTurn();
      void this.submit(blob);
    } else if (this.silenceSeconds > 0.9) this.resetTurn();
  }

  private resetTurn() {
    this.turn = []; this.preRoll = [];
    this.speechSeconds = 0; this.silenceSeconds = 0; this.turnSeconds = 0;
  }

  private async submit(blob: Blob) {
    if (!this.call || this.disposed || this.busy) return;
    this.busy = true;
    this.hooks.status("Transcribing locally");
    try {
      const result = await this.hooks.send(this.call.call_id, blob, this.request.signal);
      if (this.disposed) return;
      // #region debug-point C:local-transcription
      void fetch("http://127.0.0.1:7777/event", { method: "POST", body: JSON.stringify({ sessionId: "voice-capture", runId: "post-fix", hypothesisId: "C", msg: "[DEBUG] audio processed", data: { bytes: blob.size, heard: result.heard, status: result.call.status } }) }).catch(() => {});
      // #endregion
      this.update(result.call);
      if (!result.heard) this.hooks.status("Listening - no clear speech detected");
    } catch (error) {
      if (!this.disposed) this.fail(error instanceof Error ? error.message : "Voice request failed");
    } finally {
      this.busy = false;
    }
  }

  private speak(text: string) {
    this.resetTurn();
    this.speaking = true;
    const sequence = ++this.speechSequence;
    clearTimeout(this.speechTimer);
    window.speechSynthesis?.cancel();
    const done = () => {
      if (this.disposed || sequence !== this.speechSequence) return;
      clearTimeout(this.speechTimer);
      this.speaking = false;
      this.quietUntil = Date.now() + 300;
      if (this.call && terminal.has(this.call.status)) this.close(true);
      else this.hooks.status("Listening");
    };
    if (this.muted || !window.speechSynthesis) { done(); return; }
    this.hooks.status("Agent speaking");
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-AU";
    utterance.onend = done;
    utterance.onerror = () => {
      this.hooks.error("Browser speech playback failed. The microphone is still active; the agent's text is shown below.");
      done();
    };
    // Some browsers never emit onend; never leave the microphone gated forever.
    this.speechTimer = setTimeout(() => {
      window.speechSynthesis.cancel();
      this.hooks.error("Speech playback timed out. Listening has resumed; read the prompt in the transcript.");
      done();
    }, Math.max(10000, text.length * 100 + 5000));
    window.speechSynthesis.speak(utterance);
  }

  private fail(message: string) {
    this.hooks.error(message);
    this.close(false);
  }

  close(keepRecording: boolean) {
    if (this.disposed) return;
    this.disposed = true;
    this.request.abort();
    clearTimeout(this.speechTimer);
    clearTimeout(this.deadline);
    clearInterval(this.captureWatchdog);
    window.speechSynthesis?.cancel();
    if (keepRecording && !this.discardRecording && this.call?.consent_given && this.recording.length && this.context) {
      this.hooks.recording(wavBlob(this.recording, this.context.sampleRate));
    } else this.hooks.recording(null);
    this.recording = [];
    this.resetTurn();
    if (this.processor) {
      this.processor.port.onmessage = null;
      this.processor.disconnect();
    }
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => { track.onended = null; track.onmute = null; track.stop(); });
    if (this.context) {
      this.context.onstatechange = null;
      void this.context.close();
    }
    this.hooks.level(0);
    this.hooks.status(keepRecording ? "Call finished" : "Voice stopped");
    this.hooks.closed();
  }
}
