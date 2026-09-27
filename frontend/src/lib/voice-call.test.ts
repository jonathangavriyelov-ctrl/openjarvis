import { describe, expect, it } from 'vitest';

import {
  costLine,
  emptyVad,
  encodeWav,
  interpretRealtimeEvent,
  nextPhase,
  SPEECH_RMS,
  stepVad,
} from './voice-call';

describe('voice call', () => {
  it('names the price and the free path', () => {
    expect(costLine(0.05, 0, 'Grok')).toBe(
      'About $0.05 a minute on Grok. This call: $0.00',
    );
    expect(costLine(0, 0)).toBe('Free on this Mac. This call: $0.00');
    expect(costLine(0.3, 0.3, 'OpenAI')).toBe(
      'About $0.30 a minute on OpenAI. This call: $0.30',
    );
  });

  it('stops playback when the person starts talking', () => {
    expect(nextPhase('speaking', 'user_start')).toEqual({
      phase: 'listening',
      bargeIn: true,
    });
    expect(nextPhase('listening', 'user_end').phase).toBe('thinking');
    expect(nextPhase('thinking', 'reply_start').phase).toBe('speaking');
    expect(nextPhase('speaking', 'hangup').phase).toBe('idle');
  });

  it('hears speech, then silence, and can interrupt', () => {
    const quiet = stepVad(emptyVad(), 0.01, 0, false);
    expect(quiet.speechStart).toBe(false);
    const rising = stepVad(emptyVad(), SPEECH_RMS + 0.01, 0, true);
    const started = stepVad(rising.state, SPEECH_RMS + 0.01, 200, true);
    expect(started.speechStart).toBe(true);
    expect(started.bargeIn).toBe(true);
    const ending = stepVad(started.state, 0.01, 200, false);
    const ended = stepVad(ending.state, 0.01, 200 + 700, false);
    expect(ended.speechEnd).toBe(true);
    expect(ended.state.speaking).toBe(false);
  });

  it('reads Grok voice events', () => {
    expect(
      interpretRealtimeEvent({ type: 'response.output_audio.delta', delta: 'abc' }).kind,
    ).toBe('audio');
    expect(
      interpretRealtimeEvent({
        type: 'conversation.item.input_audio_transcription.updated',
        transcript: 'Hello',
      }),
    ).toEqual({ kind: 'user', text: 'Hello', cumulative: true, final: false });
    expect(interpretRealtimeEvent({ type: 'input_audio_buffer.speech_started' }).kind).toBe(
      'speech_started',
    );
  });

  it('wraps samples in a wav', () => {
    const wav = encodeWav(new Float32Array([0, 0.5, -0.5]), 24000);
    expect(wav.startsWith('UklGR')).toBe(true);
  });
});
