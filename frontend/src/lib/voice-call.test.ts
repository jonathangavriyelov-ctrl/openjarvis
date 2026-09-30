import { describe, expect, it } from 'vitest';

import {
  MIC_CONSTRAINTS,
  PCM_WORKLET,
  TARGET_SAMPLE_RATE,
  bargePlayback,
  chunkSampleCount,
  costLine,
  emptyVad,
  encodeWav,
  interpretRealtimeEvent,
  nextPhase,
  pickSpokenVoice,
  resampleLinear,
  SPEECH_END_MS,
  SPEECH_RMS,
  splitSentences,
  stepVad,
  timeToFirstAudio,
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
    const tooSoon = stepVad(ending.state, 0.01, 200 + SPEECH_END_MS - 1, false);
    expect(tooSoon.speechEnd).toBe(false);
    const ended = stepVad(tooSoon.state, 0.01, 200 + SPEECH_END_MS, false);
    expect(ended.speechEnd).toBe(true);
    expect(ended.state.speaking).toBe(false);
    const noisy = stepVad({ ...emptyVad(), noise: 0.05 }, 0.08, 0, false);
    expect(noisy.speechStart).toBe(false);
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
    ).toEqual({ kind: 'user', text: 'Hello', cumulative: true, final: false, itemId: '' });
    expect(interpretRealtimeEvent({ type: 'input_audio_buffer.speech_started' }).kind).toBe(
      'speech_started',
    );
    expect(interpretRealtimeEvent({ type: 'input_audio_buffer.speech_stopped' }).kind).toBe(
      'speech_stopped',
    );
    expect(interpretRealtimeEvent({ type: 'response.output_audio.done' }).kind).toBe('audio_done');
    expect(interpretRealtimeEvent({ type: 'response.done' }).kind).toBe('done');
  });

  it('captures at 24 kHz in short chunks and resamples a 48 kHz mic', () => {
    expect(TARGET_SAMPLE_RATE).toBe(24000);
    const frames = chunkSampleCount(24000);
    expect(frames).toBe(1440);
    expect(frames / 24000).toBeGreaterThanOrEqual(0.04);
    expect(frames / 24000).toBeLessThanOrEqual(0.1);
    const high = new Float32Array(480);
    const down = resampleLinear(high, 48000, 24000);
    expect(down.length).toBe(240);
    expect(resampleLinear(high, 24000, 24000)).toBe(high);
  });

  it('resets the playback cursor to now and reports the played milliseconds', () => {
    expect(bargePlayback({ next: 5, startedAt: 1.2 }, 2.5)).toEqual({
      next: 2.5,
      playedMs: 1300,
    });
    expect(bargePlayback({ next: 5, startedAt: 0 }, 2.5).playedMs).toBe(0);
    expect(timeToFirstAudio(100, 250)).toBe(150);
  });

  it('splits sentences without breaking decimals', () => {
    expect(splitSentences('The rate is 3.14 today. Next bit')).toEqual({
      ready: ['The rate is 3.14 today.'],
      rest: ' Next bit',
    });
    expect(splitSentences('Still talking', true).ready).toEqual(['Still talking']);
  });

  it('picks a natural speaking voice and asks the mic to clean itself up', () => {
    const voices = [
      { name: 'Alex', lang: 'en-US', default: true },
      { name: 'Samantha', lang: 'en-US' },
    ];
    expect(pickSpokenVoice(voices)?.name).toBe('Samantha');
    expect(pickSpokenVoice([{ name: 'Alex', lang: 'en-US', default: true }])?.name).toBe('Alex');
    const audio = MIC_CONSTRAINTS.audio as MediaTrackConstraints;
    expect(audio.echoCancellation).toBe(true);
    expect(audio.noiseSuppression).toBe(true);
    expect(audio.autoGainControl).toBe(true);
    expect(PCM_WORKLET).toContain("registerProcessor('pcm-capture'");
    expect(PCM_WORKLET).toContain('0.06');
  });

  it('wraps samples in a wav', () => {
    const wav = encodeWav(new Float32Array([0, 0.5, -0.5]), 24000);
    expect(wav.startsWith('UklGR')).toBe(true);
  });
});
