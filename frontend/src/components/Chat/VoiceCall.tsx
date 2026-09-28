import { useEffect, useRef, useState } from 'react';
import './VoiceCall.css';
import { useAppStore } from '../../lib/store';
import { modelFor, normalizeProvider, type ChatProviderId } from '../../lib/chat-providers';
import {
  MIC_CONSTRAINTS,
  PCM_WORKLET,
  TARGET_SAMPLE_RATE,
  bargePlayback,
  concatFloats,
  costLine,
  emptyVad,
  encodeWav,
  floatToPcm16,
  interpretRealtimeEvent,
  nextPhase,
  openVoiceStream,
  parseSseChunk,
  phaseLabel,
  pickSpokenVoice,
  postVoiceMetric,
  recordMetric,
  recordVoiceUsage,
  resampleLinear,
  sendVoiceTurn,
  startVoiceSession,
  stepVad,
  timeToFirstAudio,
  type VoiceLine,
  type VoicePhase,
  type VoicePlan,
} from '../../lib/voice-call';

interface VoiceCallProps {
  provider?: ChatProviderId;
  worldId?: string;
  privateCall?: boolean;
  eli5?: boolean;
  label?: string;
  storageKey?: string;
  onTranscript?: (line: VoiceLine) => void;
}

function whoPays(provider: string): string {
  if (provider === 'openai') return 'OpenAI';
  if (provider === 'claude') return 'Claude';
  if (provider === 'local') return 'this Mac';
  return 'Grok';
}

function loadLines(key?: string): VoiceLine[] {
  if (!key) return [];
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function VoiceCall({
  provider: providerProp,
  worldId = '',
  privateCall = false,
  eli5 = false,
  label,
  storageKey,
  onTranscript,
}: VoiceCallProps) {
  const activeId = useAppStore((state) => state.activeId);
  const conversations = useAppStore((state) => state.conversations);
  const draftProvider = useAppStore((state) => state.draftProvider);
  const setOpenaiNeedsCredits = useAppStore((state) => state.setOpenaiNeedsCredits);
  const conversation = conversations.find((item) => item.id === activeId);
  const provider = providerProp || normalizeProvider(conversation?.provider || draftProvider);
  const buttonLabel = label || (eli5 ? 'Talk out loud' : 'Talk to Jarvis');

  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<VoicePhase>('idle');
  const [lines, setLines] = useState<VoiceLine[]>(() => loadLines(storageKey));
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [muted, setMuted] = useState(false);
  const [usdPerMinute, setUsdPerMinute] = useState(0);
  const [spent, setSpent] = useState(0);
  const [payer, setPayer] = useState('Grok');

  const phaseRef = useRef<VoicePhase>('idle');
  const mutedRef = useRef(false);
  const linesRef = useRef<VoiceLine[]>([]);
  const modeRef = useRef<'local' | 'realtime'>('local');
  const connectedRef = useRef(false);
  const startedRef = useRef<number | null>(null);
  const voiceProviderRef = useRef('grok');
  const modelRef = useRef(modelFor(provider));
  const planRef = useRef<VoicePlan | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<AudioContext | null>(null);
  const sourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const htmlAudioRef = useRef<HTMLAudioElement | null>(null);
  const aliveRef = useRef(false);
  const itemIdRef = useRef('');
  const playbackStartRef = useRef(0);
  const earlyPcmRef = useRef<ArrayBuffer[]>([]);
  const speechStoppedRef = useRef(0);
  const ttfaLoggedRef = useRef(false);
  const audioDoneRef = useRef(false);
  const responseDoneRef = useRef(false);
  const sentenceQueueRef = useRef<{ text: string; wav: string }[]>([]);
  const generationRef = useRef(0);
  const drainingRef = useRef(false);
  const micReadyRef = useRef(false);
  const speechDoneRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);
  useEffect(() => {
    mutedRef.current = muted;
  }, [muted]);
  useEffect(() => {
    linesRef.current = lines;
  }, [lines]);

  useEffect(() => {
    if (!open || usdPerMinute <= 0) return undefined;
    const timer = window.setInterval(() => {
      const started = startedRef.current;
      if (!started) return;
      setSpent((usdPerMinute * (Date.now() - started)) / 60000);
    }, 500);
    return () => window.clearInterval(timer);
  }, [open, usdPerMinute]);

  const remember = (line: VoiceLine, replace = false, commit = true) => {
    if (!line.text.trim()) return;
    setLines((current) => {
      const next = replace && current.length && current[current.length - 1].role === line.role
        ? [...current.slice(0, -1), line]
        : [...current, line];
      if (storageKey) localStorage.setItem(storageKey, JSON.stringify(next));
      linesRef.current = next;
      return next;
    });
    if (commit) onTranscript?.(line);
  };

  const stopPlayback = () => {
    sourcesRef.current.forEach((source) => {
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
    });
    sourcesRef.current = [];
    sentenceQueueRef.current = [];
    generationRef.current += 1;
    htmlAudioRef.current?.pause();
    speechDoneRef.current?.();
    speechDoneRef.current = null;
    window.speechSynthesis?.cancel();
    const context = audioRef.current as (AudioContext & { __next?: number }) | null;
    if (context) {
      context.__next = context.currentTime;
    }
    playbackStartRef.current = 0;
  };

  const releaseMic = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    audioRef.current?.close().catch(() => {});
    audioRef.current = null;
    micReadyRef.current = false;
    earlyPcmRef.current = [];
  };

  const maybeListen = () => {
    if (!sourcesRef.current.length && (audioDoneRef.current || responseDoneRef.current)) {
      setPhase('listening');
    }
  };

  const playPcmBuffer = (bytes: ArrayBuffer, sampleRate: number) => {
    const context = audioRef.current as (AudioContext & { __next?: number }) | null;
    if (!context || bytes.byteLength < 2) return;
    const samples = new Int16Array(bytes, 0, Math.floor(bytes.byteLength / 2));
    const buffer = context.createBuffer(1, samples.length, sampleRate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < samples.length; index += 1) channel[index] = samples[index] / 32768;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const startAt = Math.max(context.currentTime, context.__next || 0);
    if (!playbackStartRef.current) playbackStartRef.current = startAt;
    source.start(startAt);
    context.__next = startAt + buffer.duration;
    sourcesRef.current.push(source);
    setPhase('speaking');
    source.onended = () => {
      sourcesRef.current = sourcesRef.current.filter((item) => item !== source);
      maybeListen();
    };
  };

  const noteFirstAudio = () => {
    if (ttfaLoggedRef.current || !speechStoppedRef.current) return;
    ttfaLoggedRef.current = true;
    const elapsed = timeToFirstAudio(speechStoppedRef.current, performance.now());
    recordMetric('ttfa_ms', elapsed);
    void postVoiceMetric('ttfa_ms', elapsed).catch(() => {});
  };

  const bargeRealtime = () => {
    const context = audioRef.current as (AudioContext & { __next?: number }) | null;
    const clock = {
      next: context?.__next || 0,
      startedAt: playbackStartRef.current,
    };
    const played = context ? bargePlayback(clock, context.currentTime) : { next: 0, playedMs: 0 };
    stopPlayback();
    if (context) context.__next = played.next;
    const socket = wsRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: 'response.cancel' }));
    if (itemIdRef.current) {
      socket.send(JSON.stringify({
        type: 'conversation.item.truncate',
        item_id: itemIdRef.current,
        content_index: 0,
        audio_end_ms: played.playedMs,
      }));
    }
  };

  const speakReply = async (text: string, wav: string) => {
    const generation = generationRef.current;
    setPhase('speaking');
    if (wav) {
      const binary = atob(wav);
      const bytes = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
      const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
      await new Promise<void>((resolve) => {
        let settled = false;
        const finish = () => {
          if (settled) return;
          settled = true;
          speechDoneRef.current = null;
          URL.revokeObjectURL(url);
          resolve();
        };
        speechDoneRef.current = finish;
        const audio = new Audio(url);
        htmlAudioRef.current = audio;
        audio.onended = finish;
        audio.onerror = finish;
        audio.play().catch(finish);
      });
      return;
    }
    const voices = window.speechSynthesis?.getVoices?.() || [];
    const chosen = pickSpokenVoice(voices);
    if (!text || !chosen || generation !== generationRef.current) return;
    await new Promise<void>((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        speechDoneRef.current = null;
        resolve();
      };
      speechDoneRef.current = finish;
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.voice = chosen as SpeechSynthesisVoice;
      utterance.onend = finish;
      utterance.onerror = finish;
      window.speechSynthesis.speak(utterance);
    });
  };

  const drainSpeech = async () => {
    if (drainingRef.current) return;
    drainingRef.current = true;
    const generation = generationRef.current;
    while (sentenceQueueRef.current.length && generation === generationRef.current) {
      const next = sentenceQueueRef.current.shift();
      if (!next) break;
      await speakReply(next.text, next.wav);
    }
    drainingRef.current = false;
    if (generation === generationRef.current && aliveRef.current) setPhase('listening');
  };

  const enqueueSpeech = (text: string, wav: string) => {
    sentenceQueueRef.current.push({ text, wav });
    void drainSpeech();
  };

  const sendUtterance = async (wavB64: string) => {
    if (!aliveRef.current) return;
    setPhase(nextPhase(phaseRef.current, 'user_end').phase);
    const payload = {
      audio_base64: wavB64,
      provider,
      private: privateCall,
      eli5,
      world_id: worldId,
      messages: linesRef.current.map((line) => ({ role: line.role, content: line.text })),
    };
    try {
      const response = await openVoiceStream(payload);
      if (!response.ok || !response.body) throw new Error('The call could not answer.');
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let pending = '';
      let assistant = '';
      while (aliveRef.current) {
        const read = await reader.read();
        if (read.done) break;
        pending += decoder.decode(read.value, { stream: true });
        const parsed = parseSseChunk(pending);
        pending = parsed.rest;
        for (const item of parsed.events) {
          const data = JSON.parse(item.data);
          if (item.event === 'transcript' && data.text) {
            remember({ role: 'user', text: data.text });
          } else if (item.event === 'sentence' && data.text) {
            assistant = assistant ? `${assistant} ${data.text}` : data.text;
            remember({
              role: 'assistant',
              text: assistant,
              model: modelRef.current,
              label: whoPays(provider),
            }, true, false);
            enqueueSpeech(data.text, data.audio_base64 || '');
          } else if (item.event === 'done') {
            if (data.needs_credits) setOpenaiNeedsCredits(true);
            if (data.content) {
              remember({
                role: 'assistant',
                text: data.content,
                model: data.model,
                label: data.label,
                note: data.note,
              }, true, true);
            }
          }
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The call could not answer.');
      setPhase('listening');
    }
  };

  const watchMic = async (plan: VoicePlan) => {
    void plan;
    if (micReadyRef.current) return;
    micReadyRef.current = true;
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('The microphone is blocked. You can still try a practice line.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
      if (!aliveRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      let context: AudioContext;
      try {
        context = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
      } catch {
        context = new AudioContext();
      }
      audioRef.current = context;
      const source = context.createMediaStreamSource(stream);
      let vad = emptyVad();
      let chunks: Float32Array[] = [];
      const onSamples = (input: Float32Array) => {
        if (!aliveRef.current || mutedRef.current) return;
        const samples = resampleLinear(input, context.sampleRate, TARGET_SAMPLE_RATE);
        if (modeRef.current === 'realtime') {
          const pcm = floatToPcm16(samples);
          const socket = wsRef.current;
          if (socket && socket.readyState === WebSocket.OPEN) {
            earlyPcmRef.current.forEach((chunk) => socket.send(chunk));
            earlyPcmRef.current = [];
            socket.send(pcm);
          } else {
            earlyPcmRef.current.push(pcm);
          }
          return;
        }
        let sum = 0;
        for (let index = 0; index < samples.length; index += 1) sum += samples[index] * samples[index];
        const rms = Math.sqrt(sum / Math.max(1, samples.length));
        const busy = phaseRef.current === 'speaking' || phaseRef.current === 'thinking' || drainingRef.current;
        const step = stepVad(vad, rms, performance.now(), busy);
        vad = step.state;
        if (step.bargeIn) {
          stopPlayback();
          setPhase('listening');
        }
        if (step.speechStart) chunks = [];
        if (vad.speaking) chunks.push(samples);
        if (step.speechEnd && chunks.length) {
          const wav = encodeWav(concatFloats(chunks), TARGET_SAMPLE_RATE);
          chunks = [];
          void sendUtterance(wav);
        }
      };
      let usedWorklet = false;
      if (context.audioWorklet) {
        try {
          const blob = new Blob([PCM_WORKLET], { type: 'application/javascript' });
          const url = URL.createObjectURL(blob);
          await context.audioWorklet.addModule(url);
          URL.revokeObjectURL(url);
          const node = new AudioWorkletNode(context, 'pcm-capture');
          node.port.onmessage = (event) => onSamples(event.data as Float32Array);
          source.connect(node);
          usedWorklet = true;
        } catch {
          usedWorklet = false;
        }
      }
      if (!usedWorklet) {
        const processor = context.createScriptProcessor(2048, 1, 1);
        source.connect(processor);
        const sink = context.createGain();
        sink.gain.value = 0;
        processor.connect(sink);
        sink.connect(context.destination);
        processor.onaudioprocess = (event) => {
          onSamples(event.inputBuffer.getChannelData(0));
        };
      }
    } catch {
      setError('The microphone is blocked. You can still try a practice line.');
    }
  };

  const openRealtime = (plan: VoicePlan) => {
    try {
      const socket = new WebSocket(plan.url, [plan.protocol]);
      wsRef.current = socket;
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        connectedRef.current = true;
        startedRef.current = Date.now();
        if (plan.session_update && Object.keys(plan.session_update).length) {
          socket.send(JSON.stringify(plan.session_update));
        }
        earlyPcmRef.current.forEach((chunk) => socket.send(chunk));
        earlyPcmRef.current = [];
        setPhase('listening');
      };
      socket.onmessage = (message) => {
        if (message.data instanceof ArrayBuffer) {
          noteFirstAudio();
          audioDoneRef.current = false;
          playPcmBuffer(message.data, plan.sample_rate || TARGET_SAMPLE_RATE);
          return;
        }
        let event: { type?: string; delta?: string; transcript?: string; item_id?: string };
        try {
          event = JSON.parse(String(message.data));
        } catch {
          return;
        }
        const parsed = interpretRealtimeEvent(event);
        if (parsed.itemId) itemIdRef.current = parsed.itemId;
        if (parsed.kind === 'speech_started') {
          bargeRealtime();
          audioDoneRef.current = false;
          responseDoneRef.current = false;
          setPhase('listening');
        } else if (parsed.kind === 'speech_stopped') {
          speechStoppedRef.current = performance.now();
          ttfaLoggedRef.current = false;
          setPhase('thinking');
        } else if (parsed.kind === 'audio') {
          noteFirstAudio();
          const binary = atob(parsed.text);
          const bytes = new Uint8Array(binary.length);
          for (let index = 0; index < binary.length; index += 1) {
            bytes[index] = binary.charCodeAt(index);
          }
          playPcmBuffer(bytes.buffer, plan.sample_rate || TARGET_SAMPLE_RATE);
        } else if (parsed.kind === 'audio_done') {
          audioDoneRef.current = true;
          maybeListen();
        } else if (parsed.kind === 'user') {
          remember({ role: 'user', text: parsed.text }, parsed.cumulative, parsed.final);
        } else if (parsed.kind === 'assistant') {
          const previous = linesRef.current[linesRef.current.length - 1];
          const text = parsed.cumulative || previous?.role !== 'assistant'
            ? parsed.text
            : `${previous.text}${parsed.text}`;
          remember({
            role: 'assistant',
            text,
            model: plan.model,
            label: whoPays(plan.provider),
          }, previous?.role === 'assistant', parsed.final);
        } else if (parsed.kind === 'done') {
          responseDoneRef.current = true;
          maybeListen();
        }
      };
      socket.onerror = () => {
        socket.close();
        connectedRef.current = false;
        modeRef.current = 'local';
        setUsdPerMinute(0);
        setNote('The live voice line did not connect, so this call stays on this Mac.');
        setPhase('listening');
        void watchMic(plan);
      };
    } catch {
      modeRef.current = 'local';
      setUsdPerMinute(0);
      setNote('The live voice line did not connect, so this call stays on this Mac.');
      setPhase('listening');
      void watchMic(plan);
    }
  };

  const begin = async () => {
    setOpen(true);
    setError('');
    setSpent(0);
    setPhase('connecting');
    aliveRef.current = true;
    connectedRef.current = false;
    try {
      const plan = await startVoiceSession({
        provider,
        private: privateCall,
        world_id: worldId,
      });
      if (!aliveRef.current) return;
      planRef.current = plan;
      modeRef.current = plan.mode;
      voiceProviderRef.current = plan.provider;
      modelRef.current = plan.model;
      setUsdPerMinute(plan.usd_per_minute || 0);
      setPayer(whoPays(plan.mode === 'realtime' ? plan.provider : 'local'));
      setNote(plan.note || '');
      if (plan.needs_credits) setOpenaiNeedsCredits(true);
      if (plan.mode === 'realtime' && plan.url && plan.protocol) {
        void watchMic(plan);
        openRealtime(plan);
        return;
      }
      startedRef.current = Date.now();
      setPhase('listening');
      await watchMic(plan);
    } catch (err) {
      setPhase('idle');
      setError(err instanceof Error ? err.message : 'The call could not start.');
    }
  };

  const practice = async () => {
    if (!aliveRef.current) await begin();
    setError('');
    setPhase('thinking');
    try {
      const turn = await sendVoiceTurn({
        practice: true,
        provider,
        private: privateCall,
        eli5,
        world_id: worldId,
        messages: linesRef.current.map((line) => ({ role: line.role, content: line.text })),
      });
      if (turn.needs_credits) setOpenaiNeedsCredits(true);
      if (turn.transcript) remember({ role: 'user', text: turn.transcript });
      if (turn.content) {
        remember({
          role: 'assistant',
          text: turn.content,
          model: turn.model,
          label: turn.label,
          note: turn.note,
        });
      }
      await speakReply(turn.content, turn.audio_base64);
      if (aliveRef.current) setPhase('listening');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The practice line did not go through.');
      setPhase('listening');
    }
  };

  const hangUp = async () => {
    const seconds = startedRef.current ? (Date.now() - startedRef.current) / 1000 : 0;
    const connected = connectedRef.current;
    const mode = modeRef.current;
    aliveRef.current = false;
    stopPlayback();
    releaseMic();
    setOpen(false);
    setPhase('idle');
    startedRef.current = null;
    try {
      await recordVoiceUsage({
        mode,
        provider: voiceProviderRef.current,
        seconds,
        connected,
        world_id: worldId,
        model: modelRef.current,
        specialist_id: worldId ? 'chief_of_staff' : 'desk',
      });
    } catch {
      /* the ledger can miss a hangup; the call itself already ended */
    }
  };

  useEffect(() => () => {
    aliveRef.current = false;
    stopPlayback();
    releaseMic();
  }, []);

  return (
    <div className="voice-call">
      <button
        type="button"
        className="voice-call-button"
        aria-pressed={open}
        aria-label={buttonLabel}
        onClick={() => {
          if (open) void hangUp();
          else void begin();
        }}
      >
        {open ? 'On a call' : buttonLabel}
      </button>
      {open && (
        <section className="voice-panel" aria-label="Call with Jarvis">
          <p className="voice-panel-status">{phaseLabel(phase)}</p>
          {note && <p className="voice-panel-note">{note}</p>}
          <p className="voice-panel-cost">{costLine(usdPerMinute, spent, payer)}</p>
          {error && <p className="voice-panel-error">{error}</p>}
          <ul className="voice-transcript">
            {lines.map((line, index) => (
              <li key={`${line.role}-${index}`}>
                <strong>{line.role === 'user' ? 'You' : line.label || 'Jarvis'}</strong>
                {line.text}
                {line.note ? <span className="voice-panel-note">{line.note}</span> : null}
              </li>
            ))}
          </ul>
          <div className="voice-panel-actions">
            <button type="button" onClick={() => setMuted((value) => !value)} aria-pressed={muted}>
              {muted ? 'Unmute' : 'Mute'}
            </button>
            <button type="button" onClick={() => void practice()}>
              Try a practice line
            </button>
            <button type="button" className="voice-hangup" onClick={() => void hangUp()}>
              Hang up
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
