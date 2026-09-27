import { useEffect, useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchAgent, routeLabel, sendPersonalChat, statusLabel, type PersonalAgent } from '../../lib/personal-api';
import { ProviderSwitcher } from '../../components/Chat/ProviderSwitcher';
import {
  normalizeProvider,
  readStoredProvider,
  writeStoredProvider,
  type ChatProviderId,
} from '../../lib/chat-providers';
import { OsError, OsShell, useDeskWorld, useEli5 } from './Shell';
import './personal.css';

interface AgentTurn {
  role: 'user' | 'assistant';
  content: string;
  label?: string;
  model?: string;
  note?: string;
}

export function AgentPage() {
  const { agentId = '' } = useParams();
  const deskWorld = useDeskWorld();
  const eli5 = useEli5();
  const [agent, setAgent] = useState<PersonalAgent | null>(null);
  const [error, setError] = useState('');
  const chatKey = `openjarvis-agent-chat:${deskWorld || 'all'}:${agentId}`;
  const [provider, setProvider] = useState<ChatProviderId>('grok');
  const [thread, setThread] = useState<AgentTurn[]>([]);
  const [question, setQuestion] = useState('');
  const [sending, setSending] = useState(false);
  const staysLocal = agentId === 'executive_assistant' || Boolean(agent?.prefers_hermes);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(chatKey);
      if (!raw) {
        setProvider(readStoredProvider(`${chatKey}:provider`));
        setThread([]);
        return;
      }
      const saved = JSON.parse(raw) as { provider?: string; messages?: AgentTurn[] };
      setProvider(normalizeProvider(saved.provider));
      setThread(Array.isArray(saved.messages) ? saved.messages : []);
    } catch {
      setProvider('grok');
      setThread([]);
    }
  }, [chatKey]);

  useEffect(() => {
    try {
      localStorage.setItem(chatKey, JSON.stringify({ provider, messages: thread }));
    } catch {
      /* private mode */
    }
  }, [chatKey, provider, thread]);

  const onAsk = async (event: FormEvent) => {
    event.preventDefault();
    const text = question.trim();
    if (!text || sending) return;
    const next = [...thread, { role: 'user' as const, content: text }];
    setThread(next);
    setQuestion('');
    setSending(true);
    setError('');
    try {
      const reply = await sendPersonalChat({
        messages: next.map((item) => ({ role: item.role, content: item.content })),
        provider,
        private: staysLocal,
        eli5,
        world_id: deskWorld || '',
      });
      setThread([
        ...next,
        {
          role: 'assistant',
          content: reply.content,
          label: reply.label,
          model: reply.model,
          note: reply.note,
        },
      ]);
    } catch {
      setThread([
        ...next,
        { role: 'assistant', content: 'Nobody could answer just now.' },
      ]);
    } finally {
      setSending(false);
    }
  };

  useEffect(() => {
    let stop = false;
    const pull = () => {
      fetchAgent(agentId, deskWorld)
        .then((data) => {
          if (!stop) {
            setAgent(data);
            setError('');
          }
        })
        .catch((err: Error) => {
          if (!stop) setError(err.message);
        });
    };
    pull();
    const timer = window.setInterval(pull, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [agentId, deskWorld]);

  return (
    <OsShell
      eyebrow={agent?.niche ? agent.niche.toUpperCase() : 'SPECIALIST'}
      title={agent?.name ?? 'Agent'}
      lede={agent?.description ?? 'Loading this specialist.'}
      action={<Link className="os-ghost" to="/os/world">Back to the world</Link>}
    >
      {error && <OsError message={error} />}
      {agent && (
        <div className="agent-hero">
          <article className="os-card">
            <p className="organism-status" style={{ color: 'var(--color-text)' }}>
              <span className="organism-dot" style={{ background: agent.accent }} />
              {statusLabel(agent.status)}
            </p>
            <p className="muted" style={{ marginTop: 8 }}>{agent.current_work || 'Waiting for the chief of staff.'}</p>
            <h2 style={{ marginTop: 16 }}>What Jarvis learned</h2>
            {(agent.learned ?? []).length === 0 && (
              <p className="muted">Nothing taught to this agent yet.</p>
            )}
            <ul>
              {(agent.learned ?? []).map((item) => (
                <li key={`${item.world_id}-${item.title}`}>
                  <strong>{item.world_name}</strong> — {item.lessons[0] || item.summary}
                </li>
              ))}
            </ul>
            <h2 style={{ marginTop: 16 }}>Procedures</h2>
            <ul className="muted">
              {(agent.skills_detail ?? []).map((skill) => (
                <li key={skill.name}><strong>{skill.name}</strong> — {skill.description}</li>
              ))}
            </ul>
            <div style={{ marginTop: 16 }}>
              <h2>Route</h2>
              <p className="muted">
                {routeLabel(agent.model)}. {agent.model?.detail}
                {agent.prefers_hermes
                  ? ' This assistant prefers a Nous Research Hermes model when that id is available.'
                  : ''}
              </p>
            </div>
          </article>
          <article className="os-card">
            <h2>Recent work</h2>
            {(agent.deliverables ?? []).length === 0 && <p className="muted">No deliverables yet.</p>}
            {(agent.deliverables ?? []).slice(0, 3).map((item) => (
              <div key={item.id} style={{ marginTop: 12 }}>
                <strong>{item.title}</strong>
                <div className="prose">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.body}</ReactMarkdown>
                </div>
              </div>
            ))}
          </article>
        </div>
      )}
      <form className="os-card" style={{ marginTop: 16 }} onSubmit={onAsk}>
        <h2>{eli5 ? 'Ask this helper' : 'Ask this agent'}</h2>
        {staysLocal && (
          <p className="muted">
            {eli5
              ? 'This helper stays on this Mac.'
              : 'Private work stays on Hermes on your Mac.'}
          </p>
        )}
        <div style={{ margin: '8px 0 12px' }}>
          <ProviderSwitcher
            eli5={eli5}
            value={staysLocal ? 'local' : provider}
            onChange={(next) => {
              if (staysLocal) return;
              setProvider(next);
              writeStoredProvider(`${chatKey}:provider`, next);
            }}
          />
        </div>
        <div className="stack">
          {thread.map((turn, index) => (
            <div key={`${turn.role}-${index}`}>
              <strong>{turn.role === 'user' ? 'You' : (turn.label || 'Answer')}</strong>
              {turn.model && <div className="reply-model">{turn.model}</div>}
              {turn.note && <p className="reply-note">{turn.note}</p>}
              <div className="prose">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{turn.content}</ReactMarkdown>
              </div>
            </div>
          ))}
        </div>
        <label className="os-label" htmlFor="agent-ask">{eli5 ? 'What do you want?' : 'Message'}</label>
        <textarea
          id="agent-ask"
          className="os-area"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder={eli5 ? 'Ask in plain words.' : 'Ask this agent about its work.'}
        />
        <div style={{ marginTop: 12 }}>
          <button className="os-button" type="submit" disabled={sending || !question.trim()}>
            {sending ? 'Sending…' : 'Send'}
          </button>
        </div>
      </form>
    </OsShell>
  );
}
