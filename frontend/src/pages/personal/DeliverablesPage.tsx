import { useEffect, useState } from 'react';
import { Link } from 'react-router';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { fetchDeliverables, fetchWorld, type Deliverable, type PersonalAgent } from '../../lib/personal-api';
import { OsError, OsShell, useEli5 } from './Shell';
import './personal.css';

export function DeliverablesPage() {
  const eli5 = useEli5();
  const [items, setItems] = useState<Deliverable[]>([]);
  const [agents, setAgents] = useState<PersonalAgent[]>([]);
  const [filter, setFilter] = useState('');
  const [open, setOpen] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchDeliverables(filter)
      .then((data) => {
        setItems(data.deliverables);
        setError('');
      })
      .catch((err: Error) => setError(err.message));
  }, [filter]);

  useEffect(() => {
    fetchWorld().then((world) => setAgents(world.agents)).catch(() => {});
  }, []);

  const nameFor = (id: string) => agents.find((agent) => agent.id === id)?.name ?? id;

  return (
    <OsShell
      eyebrow={eli5 ? 'DONE' : 'LIBRARY'}
      title={eli5 ? 'Finished work' : 'Deliverables'}
      lede={
        eli5
          ? 'This is the work the helpers finished. Open one to read it. Pictures show up when Higgsfield is connected.'
          : 'Finished work the chief collected. Marketing pieces can include a Higgsfield picture or short video when a key is set.'
      }
    >
      {error && <OsError message={error} />}
      <div className="chip-row">
        <button type="button" className={`chip-button ${filter === '' ? 'is-active' : ''}`} onClick={() => setFilter('')}>All</button>
        {agents.filter((agent) => agent.id !== 'chief_of_staff').map((agent) => (
          <button
            key={agent.id}
            type="button"
            className={`chip-button ${filter === agent.id ? 'is-active' : ''}`}
            onClick={() => setFilter(agent.id)}
          >
            {agent.name}
          </button>
        ))}
      </div>
      <div className="stack">
        {items.map((item) => (
          <article key={item.id} className="library-card">
            <div className="library-top">
              <div>
                <h2>{item.title}</h2>
                <p className="muted">
                  <Link to={`/os/agents/${item.specialist_id}`}>{nameFor(item.specialist_id)}</Link>
                  {' · '}{item.kind}
                  {item.model_source ? ` · ${item.model_source}${item.model_id ? ` (${item.model_id})` : ''}` : ''}
                </p>
              </div>
              <button className="os-ghost" type="button" onClick={() => setOpen(open === item.id ? null : item.id)}>
                {open === item.id ? 'Hide' : 'Read'}
              </button>
            </div>
            {open === item.id && (
              <div className="prose">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{item.body}</ReactMarkdown>
                {!!item.media?.length && (
                  <div className="media-row">
                    {item.media.map((asset) =>
                      asset.url && asset.kind === 'video' ? (
                        <video key={asset.id} src={asset.url} controls />
                      ) : asset.url ? (
                        <img key={asset.id} src={asset.url} alt={asset.prompt || 'Generated picture'} />
                      ) : (
                        <p key={asset.id} className="muted">{asset.detail}</p>
                      ),
                    )}
                  </div>
                )}
              </div>
            )}
          </article>
        ))}
        {items.length === 0 && <p className="muted">The library is empty until the chief brings work back.</p>}
      </div>
    </OsShell>
  );
}
