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

function planetSpot(index: number, count: number) {
  const angle = -Math.PI / 2 + (index * 2 * Math.PI) / Math.max(count, 1);
  return { x: 50 + Math.cos(angle) * 32, y: 48 + Math.sin(angle) * 30 };
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
    return (
      <OsShell
        eyebrow={eli5 ? 'YOUR PLACES' : 'WORLDS'}
        title={eli5 ? 'All your worlds' : 'Archipelago'}
        lede={
          eli5
            ? 'Each planet is a life or a business. The helper in the middle can see all of them. Tap a planet to go inside.'
            : 'Each planet is a world with its own mail, projects, and team. The chief in the center connects them. Open a planet to work inside it.'
        }
      >
        {error && <OsError message={error} />}
        <section className="world archipelago" aria-label="Worlds">
          <div className="world-sky" />
          <svg className="world-flows" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            {planets.map((planet, index) => {
              const spot = planetSpot(index, planets.length);
              return (
                <line
                  key={planet.id}
                  x1={50}
                  y1={48}
                  x2={spot.x}
                  y2={spot.y}
                  className="world-flow is-done"
                />
              );
            })}
          </svg>
          <button
            type="button"
            className={`organism is-chief is-${world?.chief?.status || 'idle'}`}
            style={{ left: '50%', top: '48%' }}
            onClick={() => navigate('/os/chief')}
          >
            <span className="organism-pulse" />
            <strong>{eli5 ? 'The boss helper' : 'Chief of Staff'}</strong>
            <em>{world?.chief?.current_work || (eli5 ? 'Watches every world' : 'Routes across worlds')}</em>
          </button>
          {planets.map((planet, index) => {
            const spot = planetSpot(index, planets.length);
            return (
              <button
                key={planet.id}
                type="button"
                className="planet"
                style={{ left: `${spot.x}%`, top: `${spot.y}%`, borderColor: planet.accent }}
                onClick={() => setDeskWorld(planet.id)}
              >
                <span className="planet-glow" style={{ background: planet.accent }} />
                <strong>{planet.name}</strong>
                <em>{planet.kind === 'personal' ? 'Personal' : 'Business'}</em>
                <small>
                  {planet.project_count} projects · {planet.goal_count} goals · {planet.agent_count} agents
                </small>
              </button>
            );
          })}
        </section>
        <section className="panel">
          <div className="panel-head">
            <h2>{eli5 ? 'Add a business' : 'New world'}</h2>
          </div>
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
            <button className="os-primary" type="submit">Create world</button>
          </form>
        </section>
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
          ? 'Each garden is a project. The plants are goals. The helpers stand on the project they are working on.'
          : 'Projects are living plots. Goals grow on them, and the team is drawn onto the work they are doing right now.')
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
              <small>{routeLabel(agent.model)}</small>
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

      <section className="panel">
        <div className="panel-head">
          <h2>{eli5 ? 'Mail for this world' : 'Google accounts'}</h2>
          <span className="muted">Point at a credentials file that lives outside this repository.</span>
        </div>
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
