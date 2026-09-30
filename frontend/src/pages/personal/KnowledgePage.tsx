import { useEffect, useState, type FormEvent } from 'react';
import {
  approvePlaybook,
  fetchKnowledge,
  fetchLearned,
  fetchPlaybooks,
  fetchWorlds,
  rejectPlaybook,
  removeKnowledge,
  rerouteKnowledge,
  teachKnowledge,
  uploadKnowledge,
  type DeskWorld,
  type KnowledgeItem,
  type LearnedWorld,
  type PlaybookProposal,
} from '../../lib/personal-api';
import { OsError, OsShell, useDeskWorld } from './Shell';
import './personal.css';

const AGENTS = [
  { id: '', name: 'Let the chief decide' },
  { id: 'chief_of_staff', name: 'Chief of Staff' },
  { id: 'executive_assistant', name: 'Executive Assistant' },
  { id: 'marketing_content', name: 'Marketing & Content' },
  { id: 'second_brain', name: 'Second Brain' },
];

export function KnowledgePage() {
  const deskWorld = useDeskWorld();
  const [worlds, setWorlds] = useState<DeskWorld[]>([]);
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [learned, setLearned] = useState<LearnedWorld[]>([]);
  const [playbooks, setPlaybooks] = useState<PlaybookProposal[]>([]);
  const [note, setNote] = useState('');
  const [url, setUrl] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [worldId, setWorldId] = useState('');
  const [agentId, setAgentId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    fetchKnowledge()
      .then((data) => setItems(data.items))
      .catch((err: Error) => setError(err.message));
    fetchLearned(deskWorld)
      .then((data) => setLearned(data.worlds))
      .catch((err: Error) => setError(err.message));
    fetchPlaybooks('pending')
      .then((data) => setPlaybooks(data.playbooks))
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    fetchWorlds()
      .then((data) => setWorlds(data.worlds))
      .catch((err: Error) => setError(err.message));
  }, []);

  useEffect(() => {
    refresh();
  }, [deskWorld]);

  const teach = async (event: FormEvent) => {
    event.preventDefault();
    if (!note.trim() && !url.trim() && !file) return;
    setBusy(true);
    setError('');
    try {
      if (file) {
        const form = new FormData();
        form.append('file', file);
        form.append('text', note);
        form.append('url', url);
        form.append('world_id', worldId);
        form.append('specialist_id', agentId);
        await uploadKnowledge(form);
      } else {
        await teachKnowledge({
          text: note,
          url,
          world_id: worldId,
          specialist_id: agentId,
        });
      }
      setNote('');
      setUrl('');
      setFile(null);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not teach that.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <OsShell
      eyebrow="TEACHING"
      title="Knowledge"
      lede="Paste a note, drop a file, or send a link. The chief reads it, keeps the lessons, and files them with the worlds and agents they belong to. A playbook change waits here until you approve it."
    >
      {error && <OsError message={error} />}
      <form className="os-card" onSubmit={teach}>
        <label className="os-label" htmlFor="teach-note">Note</label>
        <textarea
          id="teach-note"
          className="os-area"
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Always confirm the funder before an offer goes out."
        />
        <label className="os-label" htmlFor="teach-url" style={{ marginTop: 10 }}>Link or video</label>
        <input
          id="teach-url"
          className="os-field"
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
        />
        <label className="os-label" htmlFor="teach-file" style={{ marginTop: 10 }}>File</label>
        <input
          id="teach-file"
          className="os-field"
          key={file?.name || 'empty'}
          type="file"
          accept=".txt,.md,.pdf,.docx,text/plain"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <div className="os-grid" style={{ marginTop: 10 }}>
          <label className="os-label">
            World
            <select className="os-field" value={worldId} onChange={(event) => setWorldId(event.target.value)}>
              <option value="">Let the chief decide</option>
              {worlds.map((world) => (
                <option key={world.id} value={world.id}>{world.name}</option>
              ))}
            </select>
          </label>
          <label className="os-label">
            Agent
            <select className="os-field" value={agentId} onChange={(event) => setAgentId(event.target.value)}>
              {AGENTS.map((agent) => (
                <option key={agent.id || 'auto'} value={agent.id}>{agent.name}</option>
              ))}
            </select>
          </label>
        </div>
        <button className="os-button" style={{ marginTop: 12 }} type="submit" disabled={busy}>
          Teach Jarvis
        </button>
      </form>

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h2>Playbook changes</h2>
        </div>
        {playbooks.length === 0 && <p className="muted">Nothing is waiting. Agents only change how they work after you approve it.</p>}
        {playbooks.map((proposal) => (
          <article key={proposal.id} className="os-card" style={{ marginTop: 12 }}>
            <strong>{proposal.agent_name}</strong>
            <span className="muted"> · {proposal.world_name}</span>
            <p>{proposal.reason}</p>
            <pre className="os-area" style={{ whiteSpace: 'pre-wrap' }}>{proposal.proposed_brief}</pre>
            <button
              className="os-button"
              type="button"
              onClick={() => {
                approvePlaybook(proposal.id).then(refresh).catch((err: Error) => setError(err.message));
              }}
            >
              Approve
            </button>
            <button
              className="os-ghost"
              type="button"
              style={{ marginLeft: 8 }}
              onClick={() => {
                rejectPlaybook(proposal.id).then(refresh).catch((err: Error) => setError(err.message));
              }}
            >
              Reject
            </button>
          </article>
        ))}
      </section>

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h2>What was taught</h2>
        </div>
        {items.length === 0 && <p className="muted">Nothing has been taught yet.</p>}
        {items.map((item) => (
          <LessonCard
            key={item.id}
            item={item}
            worlds={worlds}
            onChange={refresh}
            onError={(message) => setError(message)}
          />
        ))}
      </section>

      <section className="panel" style={{ marginTop: 16 }}>
        <div className="panel-head">
          <h2>What Jarvis learned</h2>
        </div>
        {learned.length === 0 && <p className="muted">Lessons show up here by world and by agent.</p>}
        {learned.map((world) => (
          <article key={world.id} className="os-card" style={{ marginTop: 12 }}>
            <h3>{world.name}</h3>
            {world.agents.map((agent) => (
              <div key={agent.id} style={{ marginTop: 8 }}>
                <strong>{agent.name}</strong>
                <span className="muted"> · {agent.count} learned</span>
                <ul>
                  {agent.items.map((entry) => (
                    <li key={entry.id}>
                      {entry.title}
                      {entry.lessons[0] ? ` — ${entry.lessons[0]}` : ''}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </article>
        ))}
      </section>
    </OsShell>
  );
}

function LessonCard({
  item,
  worlds,
  onChange,
  onError,
}: {
  item: KnowledgeItem;
  worlds: DeskWorld[];
  onChange: () => void;
  onError: (message: string) => void;
}) {
  const [worldId, setWorldId] = useState(item.routes[0]?.world_id ?? '');
  const [agentId, setAgentId] = useState(item.routes[0]?.specialist_id ?? 'second_brain');

  return (
    <article className="os-card" style={{ marginTop: 12 }}>
      <p className="muted">{item.kind}{item.source ? ` · ${item.source}` : ''}</p>
      <h3>{item.title}</h3>
      <p>{item.summary}</p>
      {item.lessons.length > 0 && (
        <ul>
          {item.lessons.map((lesson) => (
            <li key={lesson}>{lesson}</li>
          ))}
        </ul>
      )}
      <ul>
        {item.routes.map((route) => (
          <li key={route.id}>
            {route.world_name} · {route.agent_name}
            <span className="muted"> — {route.reason}</span>
          </li>
        ))}
      </ul>
      <div className="os-grid">
        <select className="os-field" value={worldId} onChange={(event) => setWorldId(event.target.value)}>
          {worlds.map((world) => (
            <option key={world.id} value={world.id}>{world.name}</option>
          ))}
        </select>
        <select className="os-field" value={agentId} onChange={(event) => setAgentId(event.target.value)}>
          {AGENTS.filter((agent) => agent.id).map((agent) => (
            <option key={agent.id} value={agent.id}>{agent.name}</option>
          ))}
        </select>
      </div>
      <button
        className="os-button"
        type="button"
        style={{ marginTop: 8 }}
        onClick={() => {
          rerouteKnowledge(item.id, worldId, agentId)
            .then(onChange)
            .catch((err: Error) => onError(err.message));
        }}
      >
        Move
      </button>
      <button
        className="os-ghost"
        type="button"
        style={{ marginLeft: 8 }}
        onClick={() => {
          removeKnowledge(item.id)
            .then(onChange)
            .catch((err: Error) => onError(err.message));
        }}
      >
        Remove
      </button>
    </article>
  );
}
