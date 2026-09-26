import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import {
  connectAccount,
  createProject,
  createWorld,
  deleteProject,
  deleteWorld,
  disconnectAccount,
  fetchWorld,
  routeLabel,
  statusLabel,
  updateProject,
  updateTeamMember,
  updateWorld,
  type ProjectPlot,
  type WorldSnapshot,
} from '../../lib/personal-api';
import { HelpTip } from '../../components/HelpTip';
import { OsError, OsShell, setDeskWorld, useDeskWorld, useEli5 } from './Shell';
import './personal.css';

const AGENT_SPOTS: Record<string, { x: number; y: number }> = {
  chief_of_staff: { x: 50, y: 14 },
  executive_assistant: { x: 16, y: 28 },
  marketing_content: { x: 84, y: 28 },
  second_brain: { x: 50, y: 32 },
};

const SPORES = [
  [8, 10], [22, 8], [74, 9], [92, 16], [6, 48], [94, 44], [38, 8], [62, 10],
];

function agentSpot(id: string, index: number) {
  return AGENT_SPOTS[id] ?? { x: 12 + (index % 5) * 18, y: 22 };
}

function plotSpot(index: number, count: number) {
  if (count <= 1) return 50;
  const span = Math.min(76, 18 * count);
  const start = 50 - span / 2;
  return start + (index * span) / (count - 1);
}

const TRADES: Record<string, string> = {
  advance: 'MCA',
  gem: 'Jewelry',
  market: 'Kosher meat',
  home: 'Personal',
  ledger: 'Personal finance',
};

function tradeOf(world: { kind?: string; mark?: string }) {
  if (world.mark && TRADES[world.mark]) return TRADES[world.mark];
  if (world.kind === 'finance') return 'Personal finance';
  if (world.kind === 'personal') return 'Personal';
  return 'Business';
}

function PlanetMark({ mark }: { mark?: string }) {
  if (mark === 'gem') {
    return (
      <svg className="planet-mark" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 2 20 9 12 22 4 9Z" />
      </svg>
    );
  }
  if (mark === 'market') {
    return (
      <svg className="planet-mark" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3c2 4 6 5 8 8-3 1-5 4-8 10-3-6-5-9-8-10 2-3 6-4 8-8Z" />
      </svg>
    );
  }
  if (mark === 'home') {
    return (
      <svg className="planet-mark" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 11 12 4l8 7v9H4Z" />
      </svg>
    );
  }
  if (mark === 'ledger') {
    return (
      <svg className="planet-mark" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M6 3h12v18H6Z" />
        <path d="M9 8h6M9 12h6M9 16h4" />
      </svg>
    );
  }
  return (
    <svg className="planet-mark" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 18V10M10 18V6M16 18v-5M22 18H2" />
    </svg>
  );
}

const BOARD_SPOTS = [
  { column: 2, row: 1 },
  { column: 1, row: 2 },
  { column: 3, row: 2 },
  { column: 1, row: 3 },
  { column: 3, row: 3 },
];

function boardSpot(index: number) {
  return BOARD_SPOTS[index] ?? {
    column: (index % 3) + 1,
    row: 4 + Math.floor((index - BOARD_SPOTS.length) / 3),
  };
}

function openWorld(id: string, mail = false) {
  if (mail) sessionStorage.setItem('openjarvis-focus-mail', '1');
  else sessionStorage.removeItem('openjarvis-focus-mail');
  setDeskWorld(id);
}

export function WorldPage() {
  const navigate = useNavigate();
  const eli5 = useEli5();
  const deskWorld = useDeskWorld();
  const [world, setWorld] = useState<WorldSnapshot | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [freshName, setFreshName] = useState('');
  const [freshSummary, setFreshSummary] = useState('');
  const [worldName, setWorldName] = useState('');
  const [worldSummary, setWorldSummary] = useState('');
  const [accountEmail, setAccountEmail] = useState('');
  const [accountPath, setAccountPath] = useState('');

  useEffect(() => {
    let stop = false;
    const pull = () => {
      const request = deskWorld
        ? fetchWorld({ worldId: deskWorld })
        : fetchWorld({ scope: 'all' });
      request
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
    const timer = window.setInterval(pull, 1500);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, [deskWorld]);

  useEffect(() => {
    if (!deskWorld || sessionStorage.getItem('openjarvis-focus-mail') !== '1') return;
    sessionStorage.removeItem('openjarvis-focus-mail');
    document.getElementById('world-mail')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [deskWorld, world]);

  const projects = world?.projects ?? [];
  const agents = world?.agents ?? [];

  const beginEdit = (project: ProjectPlot) => {
    setEditing(project.id);
    setName(project.name);
    setSummary(project.summary);
  };

  const saveEdit = async (event: FormEvent) => {
    event.preventDefault();
    if (!editing || !name.trim()) return;
    await updateProject(editing, { name: name.trim(), summary: summary.trim() });
    setEditing(null);
    await reload();
  };

  const removeProject = async (id: string) => {
    await deleteProject(id);
    setEditing(null);
    await reload();
  };

  const addProject = async (event: FormEvent) => {
    event.preventDefault();
    if (!freshName.trim()) return;
    await createProject({
      name: freshName.trim(),
      summary: freshSummary.trim(),
      world_id: deskWorld,
    });
    setFreshName('');
    setFreshSummary('');
    await reload();
  };

  const reload = async () => {
    setWorld(await fetchWorld(deskWorld ? { worldId: deskWorld } : { scope: 'all' }));
  };

  if (!deskWorld) {
    const planets = world?.worlds ?? [];
    const cardHelp = eli5
      ? 'Projects are things you make. Goals are what you hope to finish. Agents are helpers. Connect email lets this place use a mailbox.'
      : 'Projects are the things you are building. Goals are what you want finished. Agents are the helpers on this world. Connect email links a mailbox so this world can draft mail for you.';
    return (
      <OsShell
        fit
        eyebrow={eli5 ? 'YOUR PLACES' : 'WORLDS'}
        title={eli5 ? 'All your worlds' : 'Archipelago'}
        lede={eli5 ? 'Each place is one part of your life.' : 'Each world is one part of your life or a business.'}
      >
        {error && <OsError message={error} />}
        <div className="archipelago-fit">
          <section className="archipelago-map" aria-label="Worlds">
            <p className="section-note">
              {eli5
                ? 'The helper in the middle can see every place.'
                : 'The person in the middle can help across every world.'}
            </p>
            <div className="planet-board">
              <div className="chief-node" style={{ gridColumn: 2, gridRow: 2 }}>
                <strong>{eli5 ? 'The boss helper' : 'Chief of Staff'}</strong>
                <em>{world?.chief?.current_work || (eli5 ? 'Watches every place.' : 'Looks across every world.')}</em>
                <button type="button" className="os-button" onClick={() => navigate('/os/chief')}>
                  {eli5 ? 'Ask the boss helper' : 'Ask Chief of Staff'}
                </button>
              </div>
              {planets.map((planet, index) => {
                const spot = boardSpot(index);
                const paying = planet.roi
                  ? (planet.roi.paying
                    ? (eli5 ? 'This place pays for itself.' : 'This world is paying for itself.')
                    : (eli5 ? 'This place is not paying for itself yet.' : 'This world is not paying for itself yet.'))
                  : '';
                return (
                  <article
                    key={planet.id}
                    className={`world-card is-${planet.mark || 'advance'}`}
                    style={{
                      gridColumn: spot.column,
                      gridRow: spot.row,
                      borderColor: planet.accent,
                      color: planet.accent,
                      ['--world-accent' as string]: planet.accent,
                    }}
                  >
                    <div className="world-card-top">
                      <PlanetMark mark={planet.mark} />
                      <HelpTip text={paying ? `${cardHelp} ${paying}` : cardHelp} />
                    </div>
                    <strong>{planet.name}</strong>
                    <em>{tradeOf(planet)}</em>
                    <small>
                      {planet.project_count} projects · {planet.goal_count} goals · {planet.agent_count} agents
                    </small>
                    <div className="world-card-actions">
                      <button type="button" className="os-button" onClick={() => openWorld(planet.id)}>
                        {eli5 ? 'Open this place' : 'Open world'}
                      </button>
                      <button type="button" className="os-ghost" onClick={() => openWorld(planet.id, true)}>
                        {eli5 ? 'Connect mail' : 'Connect email'}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
          <section className="panel archipelago-add">
            <div className="panel-head">
              <h2>{eli5 ? 'Add a place' : 'Add a world'}</h2>
            </div>
            <p className="section-note">
              {eli5
                ? 'Make a new place when you have another business.'
                : 'Add another business when you want its own mailbox and helpers.'}
            </p>
            <form
            className="project-form"
            onSubmit={async (event) => {
              event.preventDefault();
              if (!worldName.trim()) return;
              const created = await createWorld({
                name: worldName.trim(),
                summary: worldSummary.trim(),
              });
              setWorldName('');
              setWorldSummary('');
              setDeskWorld(created.id);
            }}
          >
            <label>
              Name
              <input value={worldName} onChange={(event) => setWorldName(event.target.value)} placeholder="Studio name" />
            </label>
            <label>
              What it is
              <input value={worldSummary} onChange={(event) => setWorldSummary(event.target.value)} />
            </label>
            <button className="os-button" type="submit">{eli5 ? 'Create this place' : 'Create world'}</button>
          </form>
        </section>
        </div>
      </OsShell>
    );
  }

  return (
    <OsShell
      eyebrow={world?.world?.kind === 'personal' ? 'PERSONAL' : 'BUSINESS'}
      title={world?.world?.name || (eli5 ? 'Your world' : 'Eco world')}
      lede={
        world?.world?.summary
        || (eli5
          ? 'Projects are the things you make, and helpers stand on the one they are doing.'
          : 'Projects, goals, and helpers for this world live here.')
      }
      action={
        <button className="os-ghost" type="button" onClick={() => setDeskWorld(null)}>
          {eli5 ? 'All worlds' : 'Back to worlds'}
        </button>
      }
    >
      {error && <OsError message={error} />}
      <section className="world" aria-label="Eco world">
        <div className="world-sky" />
        <div className="world-ground" />
        {SPORES.map(([x, y], index) => (
          <span key={index} className="spore" style={{ left: `${x}%`, top: `${y}%`, animationDelay: `${index * 0.45}s` }} />
        ))}
        <svg className="world-flows" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {(world?.edges ?? []).map((edge) => {
            const from = agentSpot(edge.from, 0);
            const to = agentSpot(edge.to, 1);
            return (
              <line
                key={`d-${edge.task_id}`}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className={`world-flow is-${edge.status} is-delegation`}
              />
            );
          })}
          {(world?.works ?? []).map((work, index) => {
            const from = agentSpot(work.from, 0);
            const plotIndex = projects.findIndex((project) => project.id === work.to);
            const x = plotSpot(Math.max(plotIndex, 0), projects.length || 1);
            return (
              <line
                key={`w-${work.from}-${work.to}-${index}`}
                x1={from.x}
                y1={from.y}
                x2={x}
                y2={68}
                className={`world-flow is-${work.status} is-work`}
              />
            );
          })}
        </svg>
        {projects.map((project, index) => (
          <button
            key={project.id || 'now'}
            type="button"
            className="plot"
            style={{ left: `${plotSpot(index, projects.length)}%`, borderColor: project.accent }}
            onClick={() => {
              if (project.id) beginEdit(project);
            }}
          >
            <span className="plot-soil" style={{ background: project.accent }} />
            <span className="stalks" aria-hidden="true">
              {(project.goals.length
                ? project.goals.slice(0, 6).map((goal) => ({ id: goal.id, progress: goal.progress }))
                : [{ id: 'seed', progress: 12 }]
              ).map((goal) => (
                <i
                  key={goal.id}
                  style={{ height: `${16 + Math.min(100, goal.progress) * 0.42}px`, background: project.accent }}
                />
              ))}
            </span>
            <strong>{project.name}</strong>
            <em>{project.summary}</em>
            {project.example && <span className="example-tag">Example — edit or remove</span>}
            <ul>
              {project.goals.slice(0, 2).map((goal) => (
                <li key={goal.id}>{goal.title} · {Math.round(goal.progress)}%</li>
              ))}
              {project.tasks.slice(0, 2).map((task) => (
                <li key={task.id}>{statusLabel(task.status, eli5)} · {task.title}</li>
              ))}
            </ul>
          </button>
        ))}
        {agents.map((agent, index) => {
          const spot = agentSpot(agent.id, index);
          return (
            <button
              key={agent.id}
              type="button"
              className={`organism is-${agent.status}`}
              style={{ left: `${spot.x}%`, top: `${spot.y}%`, ['--accent' as string]: agent.accent }}
              onClick={() => navigate(agent.id === 'chief_of_staff' ? '/os/chief' : `/os/agents/${agent.id}`)}
            >
              <span className="organism-pulse" />
              <span className="organism-head">
                <strong>{agent.name}</strong>
                <span className={`status-dot is-${agent.status}`}>{statusLabel(agent.status, eli5)}</span>
              </span>
              <em>{agent.current_work || (eli5 ? 'Nothing right now' : agent.niche)}</em>
              <small>
                {routeLabel(agent.model)}
                {(agent.learned_count ?? 0) > 0 ? ` · ${agent.learned_count} learned` : ''}
              </small>
            </button>
          );
        })}
        <p className="world-legend">
          {eli5
            ? 'Gardens are projects. Tall plants mean a goal is further along. A line means a helper is on that project.'
            : 'Plots are projects, stalks are goal progress, and the bright lines are helpers on that work.'}
          {world?.higgsfield?.configured ? ' Higgsfield is connected.' : ' Higgsfield pictures wait for a key.'}
          {world?.omniroute?.reachable
            ? ` Models go through OmniRoute (${world.omniroute.base_url}).`
            : world?.omniroute?.configured
              ? ` ${world.omniroute.detail}`
              : ''}
          {world?.google?.connected ? ` ${world.google.detail}` : ''}
          {world?.phone?.telegram?.listening ? ' Telegram can reach the chief.' : ''}
        </p>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>{eli5 ? 'Change a project' : 'Projects'}</h2>
          <span className="muted">{eli5 ? 'These examples are yours to rename.' : 'Quick Funders CRM and Self Audit start as examples. Rename or delete them.'}</span>
        </div>
        {editing && (
          <form className="project-form" onSubmit={saveEdit}>
            <label>
              Name
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              What it is
              <input value={summary} onChange={(event) => setSummary(event.target.value)} />
            </label>
            <button className="os-primary" type="submit">Save</button>
            <button className="os-ghost" type="button" onClick={() => removeProject(editing)}>Remove</button>
          </form>
        )}
        <form className="project-form" onSubmit={addProject}>
          <label>
            New project
            <input
              value={freshName}
              placeholder={eli5 ? 'Name the thing you are building' : 'Project name'}
              onChange={(event) => setFreshName(event.target.value)}
            />
          </label>
          <label>
            One line
            <input
              value={freshSummary}
              placeholder={eli5 ? 'What is it for?' : 'Short summary'}
              onChange={(event) => setFreshSummary(event.target.value)}
            />
          </label>
          <button className="os-primary" type="submit">Add</button>
        </form>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>{eli5 ? 'This place' : 'World'}</h2>
        </div>
        <form
          className="project-form"
          onSubmit={async (event) => {
            event.preventDefault();
            const nextName = (worldName || world?.world?.name || '').trim();
            if (!deskWorld || !nextName) return;
            await updateWorld(deskWorld, {
              name: nextName,
              summary: worldSummary || world?.world?.summary || '',
            });
            setWorldName('');
            setWorldSummary('');
            await reload();
          }}
        >
          <label>
            Rename
            <input
              value={worldName}
              placeholder={world?.world?.name || 'Name'}
              onChange={(event) => setWorldName(event.target.value)}
            />
          </label>
          <label>
            Summary
            <input
              value={worldSummary}
              placeholder={world?.world?.summary || 'What this world is for'}
              onChange={(event) => setWorldSummary(event.target.value)}
            />
          </label>
          <button className="os-primary" type="submit">Save world</button>
          {world?.world?.kind !== 'personal' && (
            <button
              className="os-ghost"
              type="button"
              onClick={async () => {
                if (!deskWorld) return;
                await deleteWorld(deskWorld);
                setDeskWorld(null);
              }}
            >
              Delete world
            </button>
          )}
        </form>
      </section>

      <section className="panel">
        <div className="panel-head">
          <h2>{eli5 ? 'Helpers here' : 'Team'}</h2>
          <span className="muted">Each world can turn helpers on, pick an OmniRoute model, and choose who may use Higgsfield.</span>
        </div>
        <ul className="team-list">
          {agents.map((agent) => (
            <li key={agent.id}>
              <strong>{agent.name}</strong>
              <label>
                <input
                  type="checkbox"
                  checked={agent.enabled !== false}
                  onChange={async (event) => {
                    await updateTeamMember(deskWorld, agent.id, { enabled: event.target.checked });
                    await reload();
                  }}
                />
                On
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={Boolean(agent.higgsfield_enabled)}
                  onChange={async (event) => {
                    await updateTeamMember(deskWorld, agent.id, { higgsfield: event.target.checked });
                    await reload();
                  }}
                />
                Higgsfield
              </label>
              <input
                className="os-field"
                defaultValue={agent.brief || ''}
                placeholder="What this helper knows about the world"
                onBlur={async (event) => {
                  if ((event.target.value || '') === (agent.brief || '')) return;
                  await updateTeamMember(deskWorld, agent.id, { brief: event.target.value });
                  await reload();
                }}
              />
              <input
                className="os-field"
                defaultValue={agent.omniroute_model || ''}
                placeholder="OmniRoute model"
                onBlur={async (event) => {
                  if ((event.target.value || '') === (agent.omniroute_model || '')) return;
                  await updateTeamMember(deskWorld, agent.id, { omniroute_model: event.target.value });
                  await reload();
                }}
              />
            </li>
          ))}
        </ul>
      </section>

      <section className="panel" id="world-mail">
        <div className="panel-head">
          <h2>{eli5 ? 'Mail for this place' : 'Connect email'}</h2>
          <span className="muted">{eli5 ? 'Add the mailbox this place should use.' : 'Add the mailbox this world should use.'}</span>
        </div>
        {(world?.accounts ?? []).length === 0 && (
          <p className="connect-mail" role="status">
            Connect email for {world?.world?.name || 'this world'}. No Google account is assigned yet.
          </p>
        )}
        <ul className="team-list">
          {(world?.accounts ?? []).map((account) => (
            <li key={account.id}>
              <strong>{account.email}</strong>
              <span className="muted">{account.connected ? 'Connected' : 'Not connected'}</span>
              <button
                className="os-ghost"
                type="button"
                onClick={async () => {
                  await disconnectAccount(deskWorld, account.id);
                  await reload();
                }}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
        <form
          className="project-form"
          onSubmit={async (event) => {
            event.preventDefault();
            if (!accountEmail.trim()) return;
            try {
              await connectAccount(deskWorld, {
                email: accountEmail.trim(),
                credentials_path: accountPath.trim(),
                label: accountEmail.trim(),
              });
              setAccountEmail('');
              setAccountPath('');
              setError('');
              await reload();
            } catch (err) {
              setError(err instanceof Error ? err.message : 'Could not attach that account.');
            }
          }}
        >
          <label>
            Email
            <input value={accountEmail} onChange={(event) => setAccountEmail(event.target.value)} placeholder="you@company.com" />
          </label>
          <label>
            Credentials file
            <input value={accountPath} onChange={(event) => setAccountPath(event.target.value)} placeholder="/home/you/.openjarvis/google-business.json" />
          </label>
          <button className="os-primary" type="submit">Assign account</button>
        </form>
      </section>
    </OsShell>
  );
}
