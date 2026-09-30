import { useEffect, useState } from 'react';
import { fetchCrm, type CrmSnapshot } from '../../lib/personal-api';
import { OsError, OsShell, useEli5 } from './Shell';
import './personal.css';

function money(amount: number) {
  return `$${amount.toLocaleString('en-US')}`;
}

export function CrmPage() {
  const eli5 = useEli5();
  const [role, setRole] = useState('owner');
  const [board, setBoard] = useState<CrmSnapshot | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let stop = false;
    fetchCrm(role)
      .then((data) => {
        if (!stop) {
          setBoard(data);
          setError('');
        }
      })
      .catch((err: Error) => {
        if (!stop) setError(err.message);
      });
    return () => {
      stop = true;
    };
  }, [role]);

  const stages = board?.stages ?? [];
  const deals = board?.deals ?? [];

  return (
    <OsShell
      eyebrow={eli5 ? 'DEALS' : 'QUICK FUNDERS'}
      title={eli5 ? 'Deals' : 'CRM'}
      lede={
        eli5
          ? 'A sample board of funding deals. Nothing here is the real customer list.'
          : 'A sample merchant-cash-advance board. Jarvis does not read or write the live Quick Funders CRM.'
      }
    >
      {error && <OsError message={error} />}
      {board && (
        <>
          <p className="crm-banner" role="status">
            {board.connection.label}
            {board.connection.read_only_url
              ? ' A future read-only address is saved and is not being called.'
              : ' No live address is set.'}
          </p>

          <section className="panel">
            <div className="panel-head">
              <h2>{eli5 ? 'How fast and how much' : 'This month'}</h2>
            </div>
            <div className="os-grid">
              <article className="os-card">
                <p className="muted">{eli5 ? 'How long until the first call' : 'Average first response'}</p>
                <strong>{board.metrics.response_minutes} min</strong>
              </article>
              <article className="os-card">
                <p className="muted">{eli5 ? 'Deals that got money' : 'Funded deals'}</p>
                <strong>
                  {board.metrics.funded_count} · {money(board.metrics.funded_volume)}
                </strong>
              </article>
            </div>
          </section>

          {board.alerts.length > 0 && (
            <section className="panel">
              <div className="panel-head">
                <h2>{eli5 ? 'Needs a person' : 'Alerts'}</h2>
              </div>
              <ul className="team-list">
                {board.alerts.map((alert) => (
                  <li key={`${alert.kind}-${alert.deal_id}`}>
                    <strong>{alert.business}</strong>
                    <span>{alert.text}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section className="panel">
            <div className="panel-head">
              <h2>{eli5 ? 'Who is looking' : 'Role'}</h2>
              <span className="muted">
                {board.roles.find((item) => item.id === board.role)?.detail}
              </span>
            </div>
            <div className="chip-row" role="tablist" aria-label="Role">
              {board.roles.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={`chip-button ${board.role === item.id ? 'is-active' : ''}`}
                  onClick={() => setRole(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>{eli5 ? 'Where each deal is' : 'Pipeline'}</h2>
            </div>
            <div className="crm-board">
              {stages.map((stage) => {
                const column = deals.filter((deal) => deal.stage === stage);
                if (!column.length) return null;
                return (
                  <article key={stage} className="os-card">
                    <h3>{stage}</h3>
                    {column.map((deal) => (
                      <div key={deal.id} className="crm-deal">
                        <strong>{deal.business}</strong>
                        <p>{money(deal.amount)} · {deal.industry}</p>
                        <p>
                          {deal.consent === 'do-not-contact'
                            ? 'Do not contact'
                            : deal.consent === 'yes'
                              ? 'Consent is on file'
                              : 'Consent is missing'}
                        </p>
                        {deal.next_action && (
                          <p>Next: {deal.next_action}{deal.next_action_on ? ` · ${deal.next_action_on}` : ''}</p>
                        )}
                        {deal.phone && <p className="muted">{deal.phone}</p>}
                        {deal.email && <p className="muted">{deal.email}</p>}
                        {deal.underwriting_note && <p className="muted">{deal.underwriting_note}</p>}
                      </div>
                    ))}
                  </article>
                );
              })}
            </div>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>{eli5 ? 'Who might fund it' : 'Funder match'}</h2>
            </div>
            <ul className="team-list">
              {board.funders.map((funder) => (
                <li key={funder.id}>
                  <strong>{funder.name}</strong>
                  <span className="muted">{funder.looks_for}</span>
                  <span>{funder.fits.length ? funder.fits.join(', ') : 'No sample deal fits'}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>{eli5 ? 'What the helpers wrote' : 'Audit log'}</h2>
            </div>
            <ul className="team-list">
              {board.audit.map((row) => (
                <li key={`${row.at}-${row.deal_id}`}>
                  <strong>{row.actor}</strong>
                  <span>{row.change}</span>
                  <span className="muted">{row.at.slice(0, 16).replace('T', ' ')}</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>Team</h2>
            </div>
            <ul className="team-list">
              {board.bots.map((bot) => (
                <li key={bot.id}>
                  <strong>{bot.name}</strong>
                  <span className="connected-badge">Connected bot</span>
                  <span className="muted">{bot.world}</span>
                  <span>{bot.role}</span>
                </li>
              ))}
            </ul>
            <pre className="crm-brief">{board.team_brief}</pre>
          </section>

          <section className="panel">
            <div className="panel-head">
              <h2>{eli5 ? 'What a good board does' : 'Checklist'}</h2>
            </div>
            <ul>
              {board.checklist.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </section>
        </>
      )}
    </OsShell>
  );
}
