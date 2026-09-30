/** Hands-free call: phases, voice activity, and the cost line. */

import { apiFetch } from './api';

export type VoicePhase = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking';

export type VoiceEvent =
  | 'connect'
  | 'user_start'
  | 'user_end'
  | 'reply_start'
  | 'reply_end'
  | 'hangup';

export interface VoiceLine {
  role: 'user' | 'assistant';
  text: string;
  model?: string;
  label?: string;
  note?: string;
}

export interface VadState {
  speaking: boolean;
  aboveSince: number | null;
  belowSince: number | null;
  noise: number;
}

export const SPEECH_RMS = 0.04;
export const SPEECH_START_MS = 150;
export const SPEECH_END_MS = 480;
export const TARGET_SAMPLE_RATE = 24000;
export const CHUNK_MS = 60;

export const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: {
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
    channelCount: 1,
  },
};

export const emptyVad = (): VadState => ({
  speaking: false,
  aboveSince: null,
  belowSince: null,
  noise: 0.01,
});

export function nextPhase(
  phase: VoicePhase,
  event: VoiceEvent,
): { phase: VoicePhase; bargeIn: boolean } {
  if (event === 'hangup') return { phase: 'idle', bargeIn: false };
  if (event === 'connect') return { phase: 'listening', bargeIn: false };
  if (event === 'user_start') {
    const bargeIn = phase === 'speaking' || phase === 'thinking';
    return { phase: 'listening', bargeIn };
  }
  if (event === 'user_end') return { phase: 'thinking', bargeIn: false };
  if (event === 'reply_start') return { phase: 'speaking', bargeIn: false };
  if (event === 'reply_end') return { phase: 'listening', bargeIn: false };
  return { phase, bargeIn: false };
}

export function costLine(usdPerMinute: number, spent: number, who = 'Grok'): string {
  const soFar = `$${(spent || 0).toFixed(2)}`;
  if (!usdPerMinute || usdPerMinute <= 0) {
    return `Free on this Mac. This call: ${soFar}`;
  }
  const rate = `$${usdPerMinute.toFixed(2)}`;
  return `About ${rate} a minute on ${who}. This call: ${soFar}`;
}

export function phaseLabel(phase: VoicePhase): string {
  if (phase === 'connecting') return 'Connecting';
  if (phase === 'listening') return 'Listening';
  if (phase === 'thinking') return 'Thinking';
  if (phase === 'speaking') return 'Speaking';
  return 'Ready';
}

export function stepVad(
  state: VadState,
  rms: number,
  now: number,
  assistantBusy: boolean,
): { state: VadState; speechStart: boolean; speechEnd: boolean; bargeIn: boolean } {
  const threshold = Math.max(SPEECH_RMS, state.noise * 3);
  const hot = rms >= threshold;
  const noise = hot ? state.noise : state.noise * 0.9 + rms * 0.1;
  const next: VadState = { ...state, noise };
  let speechStart = false;
  let speechEnd = false;
  let bargeIn = false;
  if (hot) {
    next.belowSince = null;
    if (next.aboveSince == null) next.aboveSince = now;
    if (!next.speaking && now - next.aboveSince >= SPEECH_START_MS) {
      next.speaking = true;
      speechStart = true;
      bargeIn = assistantBusy;
    }
  } else {
    next.aboveSince = null;
    if (next.speaking) {
      if (next.belowSince == null) next.belowSince = now;
      if (now - next.belowSince >= SPEECH_END_MS) {
        next.speaking = false;
        next.belowSince = null;
        speechEnd = true;
      }
    }
  }
  return { state: next, speechStart, speechEnd, bargeIn };
}

export interface RealtimeRead {
  kind:
    | 'audio'
    | 'user'
    | 'assistant'
    | 'speech_started'
    | 'speech_stopped'
    | 'audio_done'
    | 'done'
    | 'ignore';
  text: string;
  cumulative: boolean;
  final: boolean;
  itemId: string;
}

export function interpretRealtimeEvent(event: {
  type?: string;
  delta?: string;
  transcript?: string;
  item_id?: string;
  item?: { id?: string };
}): RealtimeRead {
  const type = event.type || '';
  const delta = event.delta || '';
  const transcript = event.transcript || '';
  const itemId = event.item_id || event.item?.id || '';
  const base = { text: '', cumulative: false, final: false, itemId };
  if (type === 'response.output_audio.delta' || type === 'response.audio.delta') {
    return { ...base, kind: 'audio', text: delta };
  }
  if (type === 'input_audio_buffer.speech_started') {
    return { ...base, kind: 'speech_started' };
  }
  if (type === 'input_audio_buffer.speech_stopped') {
    return { ...base, kind: 'speech_stopped' };
  }
  if (type === 'response.output_audio.done') {
    return { ...base, kind: 'audio_done', final: true };
  }
  if (type === 'conversation.item.input_audio_transcription.updated') {
    return { ...base, kind: 'user', text: transcript || delta, cumulative: true };
  }
  if (type === 'conversation.item.input_audio_transcription.completed') {
    return { ...base, kind: 'user', text: transcript || delta, cumulative: true, final: true };
  }
  if (
    type === 'response.output_audio_transcript.delta' ||
    type === 'response.audio_transcript.delta'
  ) {
    return { ...base, kind: 'assistant', text: delta || transcript };
  }
  if (type === 'response.output_audio_transcript.done') {
    return { ...base, kind: 'assistant', text: transcript || delta, cumulative: true, final: true };
  }
  if (type === 'response.done') {
    return { ...base, kind: 'done', final: true };
  }
  return { ...base, kind: 'ignore' };
}

export function encodeWav(samples: Float32Array, sampleRate: number): string {
  const bytes = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(bytes);
  const write = (offset: number, text: string) => {
    for (let index = 0; index < text.length; index += 1) {
      view.setUint8(offset + index, text.charCodeAt(index));
    }
  };
  write(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  write(8, 'WAVE');
  write(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  write(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    offset += 2;
  }
  const raw = new Uint8Array(bytes);
  let binary = '';
  for (let index = 0; index < raw.length; index += 4096) {
    binary += String.fromCharCode(...raw.subarray(index, index + 4096));
  }
  return btoa(binary);
}

export function concatFloats(chunks: Float32Array[]): Float32Array {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const merged = new Float32Array(total);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

export interface VoicePlan {
  mode: 'local' | 'realtime';
  provider: string;
  brain: string;
  model: string;
  url: string;
  protocol: string;
  token: string;
  usd_per_minute: number;
  note: string;
  needs_credits: boolean;
  sample_rate: number;
  session_update?: Record<string, unknown>;
}

export interface VoiceTurn {
  transcript: string;
  content: string;
  provider: string;
  model: string;
  label: string;
  note: string;
  needs_credits: boolean;
  audio_base64: string;
  audio_kind: string;
  sample_rate: number;
}

async function readJson<T>(path: string, body: unknown): Promise<T> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload?.detail === 'string') detail = payload.detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const startVoiceSession = (body: {
  provider: string;
  private?: boolean;
  world_id?: string;
}) => readJson<VoicePlan>('/v1/personal/voice/session', body);

export const sendVoiceTurn = (body: {
  audio_base64?: string;
  practice?: boolean;
  provider: string;
  private?: boolean;
  eli5?: boolean;
  world_id?: string;
  messages?: { role: string; content: string }[];
}) => readJson<VoiceTurn>('/v1/personal/voice/turn', body);

export function chunkSampleCount(sampleRate = TARGET_SAMPLE_RATE): number {
  return Math.round(sampleRate * (CHUNK_MS / 1000));
}

export function resampleLinear(
  input: Float32Array,
  fromRate: number,
  toRate: number,
): Float32Array {
  if (!input.length || fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.max(1, Math.round(input.length / ratio));
  const out = new Float32Array(length);
  for (let index = 0; index < length; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, input.length - 1);
    const mix = position - left;
    out[index] = input[left] * (1 - mix) + input[right] * mix;
  }
  return out;
}

export function floatToPcm16(samples: Float32Array): ArrayBuffer {
  const pcm = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    const sample = Math.max(-1, Math.min(1, samples[index]));
    pcm[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
  }
  return pcm.buffer;
}

export function bargePlayback(
  clock: { next: number; startedAt: number },
  currentTime: number,
): { next: number; playedMs: number } {
  const playedMs = clock.startedAt
    ? Math.max(0, Math.round((currentTime - clock.startedAt) * 1000))
    : 0;
  return { next: currentTime, playedMs };
}

export function timeToFirstAudio(speechStoppedAt: number, firstAudioAt: number): number {
  if (!speechStoppedAt) return 0;
  return Math.max(0, firstAudioAt - speechStoppedAt);
}

const voiceMetricLog: { name: string; value: number }[] = [];

export function recordMetric(name: string, value: number): void {
  voiceMetricLog.push({ name, value });
  console.info(`[jarvis-voice] ${name}`, value);
}

export function voiceMetrics(): { name: string; value: number }[] {
  return voiceMetricLog.slice();
}

export function resetVoiceMetrics(): void {
  voiceMetricLog.length = 0;
}

export function splitSentences(text: string, final = false): { ready: string[]; rest: string } {
  const ready: string[] = [];
  const pattern = /(?<!\d)[.!?]["']?(?=\s|$)/g;
  let start = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text))) {
    const piece = text.slice(start, match.index + match[0].length).trim();
    if (piece) ready.push(piece);
    start = match.index + match[0].length;
  }
  let rest = text.slice(start);
  if (final && rest.trim()) {
    ready.push(rest.trim());
    rest = '';
  }
  return { ready, rest };
}

export function parseSseChunk(buffer: string): {
  events: { event: string; data: string }[];
  rest: string;
} {
  const events: { event: string; data: string }[] = [];
  const parts = buffer.split('\n\n');
  const rest = parts.pop() ?? '';
  parts.forEach((part) => {
    let event = 'message';
    const dataLines: string[] = [];
    part.split('\n').forEach((line) => {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim());
    });
    if (dataLines.length) events.push({ event, data: dataLines.join('\n') });
  });
  return { events, rest };
}

export function pickSpokenVoice(
  voices: { name: string; lang: string; default?: boolean }[],
): { name: string; lang: string; default?: boolean } | null {
  const preferred = ['Samantha', 'Ava', 'Allison', 'Zoe', 'Daniel', 'Karen', 'Google US English'];
  for (const name of preferred) {
    const found = voices.find((voice) => voice.lang.startsWith('en') && voice.name.includes(name));
    if (found) return found;
  }
  return (
    voices.find((voice) => voice.lang.startsWith('en') && !voice.default) ||
    voices.find((voice) => !voice.default) ||
    voices[0] ||
    null
  );
}

export const PCM_WORKLET = `
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.pending = 0;
    this.chunks = [];
    this.target = Math.round(sampleRate * 0.06);
  }
  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel || !channel.length) return true;
    const copy = new Float32Array(channel);
    this.chunks.push(copy);
    this.pending += copy.length;
    if (this.pending >= this.target) {
      const merged = new Float32Array(this.pending);
      let offset = 0;
      for (const chunk of this.chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      this.port.postMessage(merged);
      this.chunks = [];
      this.pending = 0;
    }
    return true;
  }
}
registerProcessor('pcm-capture', PcmCaptureProcessor);
`;

export const recordVoiceUsage = (body: {
  mode: string;
  provider: string;
  seconds: number;
  connected: boolean;
  world_id?: string;
  model?: string;
  specialist_id?: string;
}) => readJson<{ amount: number; recorded: boolean }>('/v1/personal/voice/usage', body);

export const postVoiceMetric = (name: string, value: number) =>
  readJson<{ ok: boolean }>('/v1/personal/voice/metrics', { name, value });

export const openVoiceStream = (body: {
  audio_base64?: string;
  practice?: boolean;
  provider: string;
  private?: boolean;
  eli5?: boolean;
  world_id?: string;
  messages?: { role: string; content: string }[];
}) =>
  apiFetch('/v1/personal/voice/turn/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
