import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  approveProposal,
  fetchBriefing,
  fetchMission,
  fetchMissions,
  fetchPhone,
  fetchProposals,
  fetchSettings,
  rejectProposal,
  statusLabel,
  submitMission,
  type Briefing,
  type DeskCommand,
  type Mission,
  type PhoneStatus,
  type Proposal,
} from '../../lib/personal-api';
import { OsError, OsShell, useEli5 } from './Shell';
import './personal.css';

const COLUMNS = [
  { id: 'pending', label: 'Queued' },
  { id: 'working', label: 'Working' },
  { id: 'done', label: 'Done' },
];

function columnFor(status: string) {
  if (status === 'working') return 'working';
  if (status === 'done' || status === 'failed') return 'done';
  return 'pending';
}

function visibleBrief(brief: string) {
  const parts = brief.split('\n\n').map((part) => part.trim()).filter(Boolean);
  const text = parts[parts.length - 1] || brief;
  return text.length > 180 ? `${text.slice(0, 177)}…` : text;
}

export function ChiefPage() {
  const eli5 = useEli5();
  const [request, setRequest] = useState('');
  const [mission, setMission] = useState<Mission | null>(null);
  const [history, setHistory] = useState<Mission[]>([]);
  const [commands, setCommands] = useState<DeskCommand[]>([]);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [phone, setPhone] = useState<PhoneStatus | null>(null);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);

  const refreshDesk = () => {
    fetchBriefing().then(setBriefing).catch(() => {});
    fetchProposals().then((data) => setProposals(data.proposals)).catch(() => {});
    fetchPhone().then(setPhone).catch(() => {});
  };

  const refreshHistory = () => {
    fetchMissions().then((data) => setHistory(data.missions)).catch(() => {});
  };

  useEffect(() => {
    fetchMissions()
      .then((data) => {
        setHistory(data.missions);
        const latest = data.missions[0];
        if (latest) {
          fetchMission(latest.id).then(setMission).catch(() => {});
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchSettings().then((settings) => setCommands(settings.commands)).catch(() => {});
    refreshDesk();
  }, []);

  useEffect(() => {
    if (!mission || mission.status === 'completed' || mission.status === 'failed') return;
    const timer = window.setInterval(() => {
      fetchMission(mission.id)
        .then((next) => {
          setMission(next);
          if (next.status === 'completed' || next.status === 'failed') {
            refreshHistory();
            refreshDesk();
          }
        })
        .catch((err: Error) => setError(err.message));
    }, 800);
    return () => window.clearInterval(timer);
  }, [mission?.id, mission?.status]);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const text = request.trim();
    if (!text) return;
    setSending(true);
    setError('');
    try {
      const created = await submitMission(text);
      setMission(created);
      setRequest('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reach the chief of staff.');
    } finally {
      setSending(false);
    }
  };

  const tasks = mission?.tasks ?? [];

  return (
    <OsShell
      eyebrow={eli5 ? 'ASK' : 'DELEGATION'}
      title={eli5 ? 'The boss helper' : 'Chief of Staff'}
      lede={
        eli5
          ? 'Say what you want. The boss helper splits it up and gives each piece to the right helper. The buttons below are SuperClaude commands.'
          : 'Give a request, or start with a SuperClaude command. The chief routes /sc: commands to the specialists that command names, then files the finished pieces.'
      }
    >
      {error && <OsError message={error} />}
      <form className="os-card" onSubmit={onSubmit}>
        <div className="command-row">
          {commands.map((command) => (
            <button
              key={command.name}
              type="button"
              className="command-chip"
              onClick={() => setRequest(`/sc:${command.name} `)}
              title={command.summary}
            >
              /sc:{command.name}
            </button>
          ))}
        </div>
        <label className="os-label" htmlFor="chief-request">{eli5 ? 'What do you want?' : 'Request'}</label>
        <textarea
          id="chief-request"
          className="os-area"
          value={request}
          onChange={(event) => setRequest(event.target.value)}
          placeholder="Set a goal to ship the dashboard by December, draft the launch post, and remember the positioning."
        />
        <div style={{ marginTop: 12 }}>
          <button className="os-button" type="submit" disabled={sending || !request.trim()}>
            {sending ? 'Sending…' : 'Hand it to the chief'}
          </button>
        </div>
      </form>

      <div className="os-grid" style={{ marginTop: 16 }}>
        <section className="os-card">
          <h2>{eli5 ? 'Mail and meetings' : 'Inbox and calendar'}</h2>
          <p className="muted">{briefing?.google.detail || 'Google is not connected.'}</p>
          {(briefing?.inbox.length ?? 0) > 0 && (
            <ul className="muted" style={{ paddingLeft: 18 }}>
              {briefing?.inbox.slice(0, 5).map((item) => (
                <li key={`${item.from}-${item.subject}`}>
                  <strong>{item.subject}</strong>
                  {item.from ? ` — ${item.from}` : ''}
                </li>
              ))}
            </ul>
          )}
          {(briefing?.meetings.length ?? 0) > 0 && (
            <ul className="muted" style={{ paddingLeft: 18 }}>
              {briefing?.meetings.slice(0, 5).map((item) => (
                <li key={`${item.title}-${item.when}`}>
                  {item.title}{item.when ? ` — ${item.when}` : ''}
                </li>
              ))}
            </ul>
          )}
        </section>
        <section className="os-card">
          <h2>{eli5 ? 'Your phone' : 'Phone'}</h2>
          <p className="muted">{phone?.telegram.detail || 'Telegram is not connected.'}</p>
          <p className="muted">{phone?.slack.detail || 'Slack is not connected.'}</p>
        </section>
      </div>

      <section className="os-card" style={{ marginTop: 16 }}>
        <h2>{eli5 ? 'Things waiting for you' : 'Drafts waiting for approval'}</h2>
        <p className="muted">
          {eli5
            ? 'Helpers can write a draft. They cannot send it until you say yes.'
            : 'Agents file email and calendar drafts here. They do not send or change the calendar until you approve.'}
        </p>
        <div className="stack" style={{ marginTop: 12 }}>
          {proposals.map((proposal) => (
            <article key={proposal.id} className="note-card">
              <div className="note-top">
                <h2>{proposal.title}</h2>
                <span className="chip">{proposal.status}</span>
              </div>
              <p className="muted" style={{ whiteSpace: 'pre-wrap' }}>
                {proposal.payload.body || proposal.payload.description || proposal.payload.summary}
              </p>
              {proposal.detail && <p className="muted">{proposal.detail}</p>}
              {proposal.status === 'pending' && (
                <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                  <button
                    className="os-button"
                    type="button"
                    onClick={() => {
                      approveProposal(proposal.id)
                        .then(() => refreshDesk())
                        .catch((err: Error) => setError(err.message));
                    }}
                  >
                    Approve
                  </button>
                  <button
                    className="os-ghost"
                    type="button"
                    onClick={() => {
                      rejectProposal(proposal.id)
                        .then(() => refreshDesk())
                        .catch((err: Error) => setError(err.message));
                    }}
                  >
                    Reject
                  </button>
                </div>
              )}
            </article>
          ))}
          {proposals.length === 0 && <p className="muted">No drafts yet.</p>}
        </div>
      </section>

      {mission && (
        <section style={{ marginTop: 16 }}>
          <div className="os-card">
            <h2>Plan · {statusLabel(mission.status, eli5)}{mission.command ? ` · /sc:${mission.command}` : ''}</h2>
            <p className="muted">{mission.request}</p>
            {mission.plan?.length > 0 && (
              <ol className="muted" style={{ marginTop: 10, paddingLeft: 18 }}>
                {mission.plan.map((step) => (
                  <li key={step.specialist_id + step.title}>
                    <Link to={`/os/agents/${step.specialist_id}`}>{step.title}</Link>
                  </li>
                ))}
              </ol>
            )}
            {mission.summary && (
              <div className="prose" style={{ marginTop: 8 }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{mission.summary}</ReactMarkdown>
              </div>
            )}
          </div>
          <div className="board">
            {COLUMNS.map((column) => (
              <section key={column.id}>
                <h3>{column.label}</h3>
                {tasks.filter((task) => columnFor(task.status) === column.id).map((task) => (
                  <article key={task.id} className="board-card">
                    <strong>{task.title}</strong>
                    <p className="muted">{visibleBrief(task.brief)}</p>
                    <span>{task.status === 'failed' ? 'Stopped' : statusLabel(task.status)}</span>
                  </article>
                ))}
                {tasks.filter((task) => columnFor(task.status) === column.id).length === 0 && (
                  <p className="muted">Nothing here.</p>
                )}
              </section>
            ))}
          </div>
        </section>
      )}

      {history.length > 0 && (
        <section style={{ marginTop: 22 }}>
          <h2 style={{ fontSize: 16, marginBottom: 8 }}>Earlier requests</h2>
          <div className="stack">
            {history.slice(0, 6).map((item) => (
              <button
                key={item.id}
                className="os-card"
                style={{ textAlign: 'left', cursor: 'pointer' }}
                onClick={() => fetchMission(item.id).then(setMission).catch((err: Error) => setError(err.message))}
              >
                <strong>{item.request}</strong>
                <p className="muted">{statusLabel(item.status)}</p>
              </button>
            ))}
          </div>
        </section>
      )}
    </OsShell>
  );
}
