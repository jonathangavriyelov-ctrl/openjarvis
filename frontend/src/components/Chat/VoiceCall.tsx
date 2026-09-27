import { useEffect, useRef, useState } from 'react';
import './VoiceCall.css';
import { useAppStore } from '../../lib/store';
import { modelFor, normalizeProvider, type ChatProviderId } from '../../lib/chat-providers';
import {
  concatFloats,
  costLine,
  emptyVad,
  encodeWav,
  interpretRealtimeEvent,
  nextPhase,
  phaseLabel,
  recordVoiceUsage,
  sendVoiceTurn,
  startVoiceSession,
  stepVad,
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
    htmlAudioRef.current?.pause();
    window.speechSynthesis?.cancel();
  };

  const releaseMic = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    wsRef.current?.close();
    wsRef.current = null;
    audioRef.current?.close().catch(() => {});
    audioRef.current = null;
  };

  const playPcm = (b64: string, sampleRate: number) => {
    const context = audioRef.current;
    if (!context || !b64) return;
    const binary = atob(b64);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    const samples = new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
    const buffer = context.createBuffer(1, samples.length, sampleRate);
    const channel = buffer.getChannelData(0);
    for (let index = 0; index < samples.length; index += 1) channel[index] = samples[index] / 32768;
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(context.destination);
    const cursor = (context as AudioContext & { __next?: number });
    const startAt = Math.max(context.currentTime, cursor.__next || 0);
    source.start(startAt);
    cursor.__next = startAt + buffer.duration;
    sourcesRef.current.push(source);
    setPhase('speaking');
    source.onended = () => {
      sourcesRef.current = sourcesRef.current.filter((item) => item !== source);
      if (!sourcesRef.current.length && phaseRef.current === 'speaking') setPhase('listening');
    };
  };

  const speakReply = async (text: string, wav: string) => {
    stopPlayback();
    setPhase('speaking');
    const voices = window.speechSynthesis?.getVoices?.() || [];
    if (text && voices.length) {
      await new Promise<void>((resolve) => {
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.onend = () => resolve();
        utterance.onerror = () => resolve();
        window.speechSynthesis.speak(utterance);
      });
      return;
    }
    if (!wav) return;
    const binary = atob(wav);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    const url = URL.createObjectURL(new Blob([bytes], { type: 'audio/wav' }));
    await new Promise<void>((resolve) => {
      const audio = new Audio(url);
      htmlAudioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        resolve();
      };
      audio.onerror = () => resolve();
      audio.play().catch(() => resolve());
    });
  };

  const sendUtterance = async (wavB64: string) => {
    if (!aliveRef.current) return;
    setPhase(nextPhase(phaseRef.current, 'user_end').phase);
    try {
      const turn = await sendVoiceTurn({
        audio_base64: wavB64,
        provider,
        private: privateCall,
        eli5,
        world_id: worldId,
        messages: linesRef.current.map((line) => ({ role: line.role, content: line.text })),
      });
      if (!aliveRef.current) return;
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
      setError(err instanceof Error ? err.message : 'The call could not answer.');
      setPhase('listening');
    }
  };

  const watchMic = async (plan: VoicePlan) => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('The microphone is blocked. You can still try a practice line.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!aliveRef.current) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      streamRef.current = stream;
      const context = new AudioContext();
      audioRef.current = context;
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      source.connect(processor);
      const sink = context.createGain();
      sink.gain.value = 0;
      processor.connect(sink);
      sink.connect(context.destination);
      let vad = emptyVad();
      let chunks: Float32Array[] = [];
      processor.onaudioprocess = (event) => {
        if (!aliveRef.current || mutedRef.current) return;
        const input = event.inputBuffer.getChannelData(0);
        if (plan.mode === 'realtime') {
          if (wsRef.current?.readyState !== WebSocket.OPEN) return;
          const pcm = new Int16Array(input.length);
          for (let index = 0; index < input.length; index += 1) {
            const sample = Math.max(-1, Math.min(1, input[index]));
            pcm[index] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
          }
          const bytes = new Uint8Array(pcm.buffer);
          let binary = '';
          for (let index = 0; index < bytes.length; index += 4096) {
            binary += String.fromCharCode(...bytes.subarray(index, index + 4096));
          }
          wsRef.current.send(JSON.stringify({
            type: 'input_audio_buffer.append',
            audio: btoa(binary),
          }));
          return;
        }
        let sum = 0;
        for (let index = 0; index < input.length; index += 1) sum += input[index] * input[index];
        const rms = Math.sqrt(sum / Math.max(1, input.length));
        const busy = phaseRef.current === 'speaking' || phaseRef.current === 'thinking';
        const step = stepVad(vad, rms, performance.now(), busy);
        vad = step.state;
        if (step.bargeIn) {
          stopPlayback();
          setPhase('listening');
        }
        if (step.speechStart) chunks = [];
        if (vad.speaking) chunks.push(new Float32Array(input));
        if (step.speechEnd && chunks.length) {
          const wav = encodeWav(concatFloats(chunks), context.sampleRate);
          chunks = [];
          void sendUtterance(wav);
        }
      };
    } catch {
      setError('The microphone is blocked. You can still try a practice line.');
    }
  };

  const openRealtime = (plan: VoicePlan) => {
    try {
      const socket = new WebSocket(plan.url, [plan.protocol]);
      wsRef.current = socket;
      socket.onopen = () => {
        connectedRef.current = true;
        startedRef.current = Date.now();
        if (plan.session_update && Object.keys(plan.session_update).length) {
          socket.send(JSON.stringify(plan.session_update));
        }
        setPhase('listening');
        void watchMic(plan);
      };
      socket.onmessage = (message) => {
        let event: { type?: string; delta?: string; transcript?: string };
        try {
          event = JSON.parse(String(message.data));
        } catch {
          return;
        }
        const parsed = interpretRealtimeEvent(event);
        if (parsed.kind === 'speech_started') {
          const moved = nextPhase(phaseRef.current, 'user_start');
          if (moved.bargeIn) stopPlayback();
          setPhase(moved.phase);
        } else if (parsed.kind === 'audio') {
          playPcm(parsed.text, plan.sample_rate || 24000);
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
        } else if (parsed.kind === 'done' && phaseRef.current === 'speaking') {
          setPhase('listening');
        }
      };
      socket.onerror = () => {
        socket.close();
        connectedRef.current = false;
        modeRef.current = 'local';
        setUsdPerMinute(0);
        setNote('The live voice line did not connect, so this call stays on this Mac.');
        setPhase('listening');
        void watchMic({ ...plan, mode: 'local' });
      };
    } catch {
      modeRef.current = 'local';
      setUsdPerMinute(0);
      setNote('The live voice line did not connect, so this call stays on this Mac.');
      setPhase('listening');
      void watchMic({ ...plan, mode: 'local' });
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
