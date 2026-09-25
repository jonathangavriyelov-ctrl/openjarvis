import { useEffect, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router';
import {
  createProject,
  deleteProject,
  fetchWorld,
  routeLabel,
  statusLabel,
  updateProject,
  type ProjectPlot,
  type WorldSnapshot,
} from '../../lib/personal-api';
import { OsError, OsShell, useEli5 } from './Shell';
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

export function WorldPage() {
  const navigate = useNavigate();
  const eli5 = useEli5();
  const [world, setWorld] = useState<WorldSnapshot | null>(null);
  const [error, setError] = useState('');
  const [editing, setEditing] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [summary, setSummary] = useState('');
  const [freshName, setFreshName] = useState('');
  const [freshSummary, setFreshSummary] = useState('');

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
    const timer = window.setInterval(pull, 1500);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, []);

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
    const next = await fetchWorld();
    setWorld(next);
  };

  const removeProject = async (id: string) => {
    await deleteProject(id);
    setEditing(null);
    setWorld(await fetchWorld());
  };

  const addProject = async (event: FormEvent) => {
    event.preventDefault();
    if (!freshName.trim()) return;
    await createProject({ name: freshName.trim(), summary: freshSummary.trim() });
    setFreshName('');
    setFreshSummary('');
    setWorld(await fetchWorld());
  };

  return (
    <OsShell
      eyebrow={eli5 ? 'WHAT YOU ARE DOING' : 'HABITAT'}
      title={eli5 ? 'Your world' : 'Eco world'}
      lede={
        eli5
          ? 'Each garden is a project. The plants are goals. The helpers stand on the project they are working on.'
          : 'Projects are living plots. Goals grow on them, and the team is drawn onto the work they are doing right now.'
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
    </OsShell>
  );
}
