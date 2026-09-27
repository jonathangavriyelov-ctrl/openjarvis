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
}

export const SPEECH_RMS = 0.04;
export const SPEECH_START_MS = 150;
export const SPEECH_END_MS = 700;

export const emptyVad = (): VadState => ({
  speaking: false,
  aboveSince: null,
  belowSince: null,
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
  const hot = rms >= SPEECH_RMS;
  const next: VadState = { ...state };
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

export function interpretRealtimeEvent(event: { type?: string; delta?: string; transcript?: string }): {
  kind: 'audio' | 'user' | 'assistant' | 'speech_started' | 'done' | 'ignore';
  text: string;
  cumulative: boolean;
  final: boolean;
} {
  const type = event.type || '';
  const delta = event.delta || '';
  const transcript = event.transcript || '';
  if (type === 'response.output_audio.delta' || type === 'response.audio.delta') {
    return { kind: 'audio', text: delta, cumulative: false, final: false };
  }
  if (type === 'input_audio_buffer.speech_started') {
    return { kind: 'speech_started', text: '', cumulative: false, final: false };
  }
  if (type === 'conversation.item.input_audio_transcription.updated') {
    return { kind: 'user', text: transcript || delta, cumulative: true, final: false };
  }
  if (type === 'conversation.item.input_audio_transcription.completed') {
    return { kind: 'user', text: transcript || delta, cumulative: true, final: true };
  }
  if (
    type === 'response.output_audio_transcript.delta' ||
    type === 'response.audio_transcript.delta'
  ) {
    return { kind: 'assistant', text: delta || transcript, cumulative: false, final: false };
  }
  if (type === 'response.output_audio_transcript.done') {
    return { kind: 'assistant', text: transcript || delta, cumulative: true, final: true };
  }
  if (type === 'response.done') {
    return { kind: 'done', text: '', cumulative: false, final: true };
  }
  return { kind: 'ignore', text: '', cumulative: false, final: false };
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

export const recordVoiceUsage = (body: {
  mode: string;
  provider: string;
  seconds: number;
  connected: boolean;
  world_id?: string;
  model?: string;
  specialist_id?: string;
}) => readJson<{ amount: number; recorded: boolean }>('/v1/personal/voice/usage', body);
