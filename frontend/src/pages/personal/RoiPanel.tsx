import { useEffect, useState, type FormEvent } from 'react';
import {
  addRevenue,
  fetchRoi,
  fetchWorlds,
  saveRoiSettings,
  type DeskWorld,
  type RoiReport,
} from '../../lib/personal-api';

function money(value: number) {
  return `$${value.toFixed(2)}`;
}

export function RoiPanel() {
  const [report, setReport] = useState<RoiReport | null>(null);
  const [worlds, setWorlds] = useState<DeskWorld[]>([]);
  const [worldId, setWorldId] = useState('');
  const [amount, setAmount] = useState('');
  const [note, setNote] = useState('');
  const [costName, setCostName] = useState('Neon');
  const [costAmount, setCostAmount] = useState('');
  const [costWorld, setCostWorld] = useState('');
  const [error, setError] = useState('');

  const load = () => {
    fetchRoi()
      .then((data) => {
        setReport(data);
        setWorldId((current) => current || data.worlds[0]?.id || '');
      })
      .catch((err: Error) => setError(err.message));
  };

  useEffect(() => {
    load();
    fetchWorlds()
      .then((data) => setWorlds(data.worlds))
      .catch(() => {});
  }, []);

  if (!report) {
    return error ? <p className="os-error">{error}</p> : null;
  }

  const overall = report.overall;
  const addSale = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(amount);
    if (!worldId || !(value > 0)) return;
    addRevenue({ world_id: worldId, amount: value, note, source: 'manual' })
      .then((data) => {
        setReport(data);
        setAmount('');
        setNote('');
      })
      .catch((err: Error) => setError(err.message));
  };

  const saveBudgets = (event: FormEvent) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget as HTMLFormElement);
    const worldBudgets: Record<string, number> = {};
    for (const world of report.worlds) {
      worldBudgets[world.id] = Number(form.get(`budget-${world.id}`) || 0);
    }
    saveRoiSettings({
      hourly_rate: Number(form.get('hourly') || report.settings.hourly_rate),
      budgets: {
        overall: Number(form.get('overall') || 0),
        worlds: worldBudgets,
      },
    })
      .then(setReport)
      .catch((err: Error) => setError(err.message));
  };

  const addCost = (event: FormEvent) => {
    event.preventDefault();
    const value = Number(costAmount);
    if (!costName.trim() || !(value >= 0)) return;
    const recurring = [
      ...report.settings.recurring,
      { name: costName.trim(), amount: value, world_id: costWorld },
    ];
    saveRoiSettings({ recurring })
      .then((data) => {
        setReport(data);
        setCostAmount('');
      })
      .catch((err: Error) => setError(err.message));
  };

  return (
    <section className="os-card" style={{ marginTop: 16 }}>
      <h2>Cost and return</h2>
      <p>
        {overall.paying ? 'The desk is paying for itself this month.' : 'The desk is not paying for itself this month.'}
        {' '}
        {money(overall.cost)} cost, {money(overall.value)} value, net {money(overall.net)}.
      </p>
      <p className="muted">
        Models {money(overall.llm)} · pictures {money(overall.higgsfield)} · other {money(overall.recurring)}
        {report.gateway ? ` · OmniRoute reported ${money(report.gateway.cost)} over ${report.gateway.range}` : ''}
      </p>
      {error && <p className="os-error">{error}</p>}
      {report.alerts.map((alert) => (
        <p key={alert.id} className="muted">{alert.message}</p>
      ))}
      <ul>
        {report.worlds.map((world) => (
          <li key={world.id}>
            <strong>{world.name}</strong>
            {' '}
            {money(world.cost)} cost · {money(world.value)} value · {world.paying ? 'paying for itself' : 'not yet'}
            {world.alert === 'warn' ? ' · at 80%' : ''}
            {world.alert === 'blocked' ? ' · at the cap' : ''}
          </li>
        ))}
      </ul>
      {report.agents.length > 0 && (
        <ul className="muted">
          {report.agents.map((agent) => (
            <li key={`${agent.world_id}-${agent.specialist_id}`}>
              {agent.world_name} · {agent.agent_name} · {money(agent.cost)}
              {' '}
              ({agent.input_tokens + agent.output_tokens} tokens)
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={addSale} className="os-grid">
        <label className="os-label">
          Revenue
          <select className="os-field" value={worldId} onChange={(event) => setWorldId(event.target.value)}>
            {worlds.map((world) => (
              <option key={world.id} value={world.id}>{world.name}</option>
            ))}
          </select>
        </label>
        <label className="os-label">
          Amount
          <input className="os-field" value={amount} onChange={(event) => setAmount(event.target.value)} placeholder="1200" />
        </label>
        <label className="os-label">
          Note
          <input className="os-field" value={note} onChange={(event) => setNote(event.target.value)} placeholder="Funded deal" />
        </label>
        <button className="os-button" type="submit">Add revenue</button>
      </form>
      <form onSubmit={addCost} className="os-grid" style={{ marginTop: 12 }}>
        <label className="os-label">
          Recurring cost
          <input className="os-field" value={costName} onChange={(event) => setCostName(event.target.value)} />
        </label>
        <label className="os-label">
          Monthly amount
          <input className="os-field" value={costAmount} onChange={(event) => setCostAmount(event.target.value)} placeholder="19" />
        </label>
        <label className="os-label">
          World
          <select className="os-field" value={costWorld} onChange={(event) => setCostWorld(event.target.value)}>
            <option value="">Overall</option>
            {worlds.map((world) => (
              <option key={world.id} value={world.id}>{world.name}</option>
            ))}
          </select>
        </label>
        <button className="os-button" type="submit">Add cost</button>
      </form>
      <form onSubmit={saveBudgets} style={{ marginTop: 12 }}>
        <label className="os-label">
          Overall monthly cap
          <input className="os-field" name="overall" defaultValue={report.settings.budgets.overall} />
        </label>
        <label className="os-label">
          Hourly value of saved time
          <input className="os-field" name="hourly" defaultValue={report.settings.hourly_rate} />
        </label>
        {report.worlds.map((world) => (
          <label key={world.id} className="os-label">
            {world.name} cap
            <input
              className="os-field"
              name={`budget-${world.id}`}
              defaultValue={report.settings.budgets.worlds[world.id] ?? 0}
            />
          </label>
        ))}
        <button className="os-button" type="submit" style={{ marginTop: 8 }}>Save budgets</button>
      </form>
    </section>
  );
}
