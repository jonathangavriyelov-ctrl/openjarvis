import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { fetchWorld, statusLabel, type WorldSnapshot } from '../../lib/personal-api';
import { OsError, OsShell } from './Shell';
import './personal.css';

const PLACES: Record<string, { x: number; y: number }> = {
  chief_of_staff: { x: 50, y: 44 },
  executive_assistant: { x: 22, y: 26 },
  marketing_content: { x: 78, y: 26 },
  second_brain: { x: 50, y: 76 },
};

const SPORES = [
  [12, 18], [28, 12], [70, 14], [88, 22], [16, 62], [84, 68], [40, 18], [62, 80],
];

function placeFor(id: string, index: number) {
  return PLACES[id] ?? { x: 18 + (index % 4) * 20, y: 88 };
}

export function WorldPage() {
  const navigate = useNavigate();
  const [world, setWorld] = useState<WorldSnapshot | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let stop = false;
    const pull = () => {
      fetchWorld()
        .then((data) => {
          if (!stop) {
            setWorld(data);
            setError('');
          }
        })
        .catch((err: Error) => {
          if (!stop) setError(err.message || 'The local Jarvis server is not reachable.');
        });
    };
    pull();
    const timer = window.setInterval(pull, 2000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, []);

  const agents = world?.agents ?? [];
  const edges = world?.edges ?? [];
  const chief = placeFor('chief_of_staff', 0);

  return (
    <OsShell
      eyebrow="THE LIVING TEAM"
      title="Eco world"
      lede="The chief of staff stands in the heartwood. Specialists live in their own niches. A path lights up while work is moving, and settles when the deliverable is back."
    >
      {error && <OsError message={error} />}
      <section className="world" aria-label="Agent habitat">
        <div className="world-ground" />
        {SPORES.map(([x, y], index) => (
          <span
            key={`${x}-${y}`}
            className="spore"
            style={{ left: `${x}%`, top: `${y}%`, animationDelay: `${index * 0.6}s` }}
          />
        ))}
        <svg className="world-flows" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {edges.map((edge) => {
            const target = placeFor(edge.to, 1);
            const midX = (chief.x + target.x) / 2;
            const midY = (chief.y + target.y) / 2 - 6;
            const klass = edge.status === 'working'
              ? 'is-working'
              : edge.status === 'done'
                ? 'is-done'
                : 'is-pending';
            return (
              <path
                key={edge.task_id}
                className={`world-flow ${klass}`}
                d={`M ${chief.x} ${chief.y} Q ${midX} ${midY} ${target.x} ${target.y}`}
              />
            );
          })}
        </svg>
        {agents.map((agent, index) => {
          const spot = placeFor(agent.id, index);
          const state = agent.status === 'working' ? 'is-working' : agent.status === 'done' ? 'is-done' : 'is-idle';
          return (
            <button
              key={agent.id}
              className={`organism ${state} ${agent.id === 'chief_of_staff' ? 'is-chief' : ''}`}
              style={{ left: `${spot.x}%`, top: `${spot.y}%`, borderColor: agent.accent }}
              onClick={() => navigate(agent.id === 'chief_of_staff' ? '/os/chief' : `/os/agents/${agent.id}`)}
            >
              <small>{agent.niche}</small>
              <strong>{agent.name}</strong>
              <em>{agent.current_work || agent.title}</em>
              <span className="organism-status">
                <span className="organism-dot" />
                {statusLabel(agent.status)}
              </span>
            </button>
          );
        })}
        <div className="world-legend">
          <span><i className="swatch idle" /> Idle</span>
          <span><i className="swatch working" /> Working</span>
          <span><i className="swatch done" /> Done</span>
        </div>
      </section>
      <div className="os-grid" style={{ marginTop: 16 }}>
        <article className="os-card">
          <h2>Latest delegation</h2>
          {world?.mission ? (
            <>
              <p className="muted">{world.mission.request}</p>
              <p className="muted" style={{ marginTop: 8 }}>{statusLabel(world.mission.status)} · {edges.length} path{edges.length === 1 ? '' : 's'}</p>
            </>
          ) : (
            <p className="muted">The habitat is quiet. Give the chief of staff a request and the paths will light up.</p>
          )}
        </article>
        <article className="os-card">
          <h2>Executive Assistant model</h2>
          <p className="muted">
            {world?.hermes
              ? `${world.hermes.source === 'hermes' ? 'Hermes' : world.hermes.source === 'fallback' ? 'Fallback model' : 'Local producer'} · ${world.hermes.model_id || 'no model loaded'}`
              : 'Checking the engine…'}
          </p>
          <p className="muted" style={{ marginTop: 8 }}>{world?.hermes?.detail}</p>
        </article>
      </div>
    </OsShell>
  );
}
