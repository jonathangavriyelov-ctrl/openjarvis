import { useEffect, useState, type FormEvent } from 'react';
import { Link } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  fetchMission,
  fetchMissions,
  statusLabel,
  submitMission,
  type Mission,
} from '../../lib/personal-api';
import { OsError, OsShell } from './Shell';
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
  const [request, setRequest] = useState('');
  const [mission, setMission] = useState<Mission | null>(null);
  const [history, setHistory] = useState<Mission[]>([]);
  const [error, setError] = useState('');
  const [sending, setSending] = useState(false);

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
    if (!mission || mission.status === 'completed' || mission.status === 'failed') return;
    const timer = window.setInterval(() => {
      fetchMission(mission.id)
        .then((next) => {
          setMission(next);
          if (next.status === 'completed' || next.status === 'failed') refreshHistory();
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
      eyebrow="DELEGATION"
      title="Chief of Staff"
      lede="Give Jonathan's request here. The chief breaks it into tasks, sends each one to the specialist who owns that work, and files the finished pieces in the deliverables library."
    >
      {error && <OsError message={error} />}
      <form className="os-card" onSubmit={onSubmit}>
        <label className="os-label" htmlFor="chief-request">Request</label>
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

      {mission && (
        <section style={{ marginTop: 16 }}>
          <div className="os-card">
            <h2>Plan · {statusLabel(mission.status)}</h2>
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
