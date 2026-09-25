import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchAgent, routeLabel, statusLabel, type PersonalAgent } from '../../lib/personal-api';
import { OsError, OsShell } from './Shell';
import './personal.css';

export function AgentPage() {
  const { agentId = '' } = useParams();
  const [agent, setAgent] = useState<PersonalAgent | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let stop = false;
    const pull = () => {
      fetchAgent(agentId)
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
  }, [agentId]);

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
    </OsShell>
  );
}
