import { useEffect, useState, type FormEvent } from 'react';
import {
  createGoal,
  fetchGoals,
  fetchProjects,
  runCheckin,
  setMilestone,
  updateGoal,
  type Goal,
  type ProjectPlot,
} from '../../lib/personal-api';
import { OsError, OsShell, useDeskWorld, useEli5 } from './Shell';
import './personal.css';

export function GoalsPage() {
  const eli5 = useEli5();
  const deskWorld = useDeskWorld();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [projects, setProjects] = useState<ProjectPlot[]>([]);
  const [checkins, setCheckins] = useState(0);
  const [error, setError] = useState('');
  const [title, setTitle] = useState('');
  const [target, setTarget] = useState('');
  const [deadline, setDeadline] = useState('');
  const [projectId, setProjectId] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = () => {
    fetchGoals(deskWorld)
      .then((data) => {
        setGoals(data.goals);
        setCheckins(data.checkins.length);
        setError('');
      })
      .catch((err: Error) => setError(err.message));
    fetchProjects(deskWorld).then((data) => setProjects(data.projects.filter((item) => item.id))).catch(() => {});
  };

  useEffect(() => {
    refresh();
  }, [deskWorld]);

  const onCreate = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim()) return;
    setBusy(true);
    try {
      await createGoal({
        title: title.trim(),
        target: target.trim() || 'Completed',
        deadline: deadline ? `${deadline}T23:59:59+00:00` : null,
        project_id: projectId || null,
        world_id: deskWorld,
      });
      setTitle('');
      setTarget('');
      setDeadline('');
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the goal.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <OsShell
      eyebrow={eli5 ? 'HOW YOU ARE DOING' : 'PACE'}
      title="Goals"
      lede={
        eli5
          ? 'A goal is something you want done by a day. The badge says if you are doing fine, need to hurry, or are behind.'
          : 'Targets and deadlines live here. Put a goal on a project so it grows in that plot of the eco world.'
      }
      action={
        <button
          className="os-ghost"
          type="button"
          onClick={() => {
            setBusy(true);
            runCheckin()
              .then(() => refresh())
              .catch((err: Error) => setError(err.message))
              .finally(() => setBusy(false));
          }}
          disabled={busy}
        >
          Run today's check-in
        </button>
      }
    >
      {error && <OsError message={error} />}
      <form className="os-card form-grid" onSubmit={onCreate}>
        <label className="os-label">Goal
          <input className="os-field" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Ship the personal OS" />
        </label>
        <label className="os-label">Target
          <input className="os-field" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="Dashboard in daily use" />
        </label>
        <label className="os-label">Deadline
          <input className="os-field" type="date" value={deadline} onChange={(event) => setDeadline(event.target.value)} />
        </label>
        <label className="os-label">Project
          <select className="os-field" value={projectId} onChange={(event) => setProjectId(event.target.value)}>
            <option value="">{eli5 ? 'Not on a project yet' : 'No project'}</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
        </label>
        <button className="os-button" type="submit" disabled={busy || !title.trim()}>Add goal</button>
      </form>
      <p className="muted" style={{ margin: '12px 0' }}>{checkins} daily check-in{checkins === 1 ? '' : 's'} on the board.</p>
      <div className="stack">
        {goals.map((goal) => (
          <article key={goal.id} className="goal-card">
            <div className="goal-top">
              <div>
                <h2>{goal.title}</h2>
                <p className="muted">
                  {!deskWorld && goal.world_name ? `${goal.world_name} · ` : ''}
                  Target: {goal.target || 'Completed'}{goal.deadline ? ` · due ${goal.deadline.slice(0, 10)}` : ''}
                </p>
              </div>
              <span className={`pace ${goal.on_track}`}>{goal.pace}</span>
            </div>
            <div className="meter" aria-hidden="true"><span style={{ width: `${goal.progress}%` }} /></div>
            <label className="os-label" htmlFor={`progress-${goal.id}`}>Progress {Math.round(goal.progress)}%</label>
            <input
              id={`progress-${goal.id}`}
              type="range"
              min={0}
              max={100}
              value={goal.progress}
              onChange={(event) => {
                const progress = Number(event.target.value);
                setGoals((current) => current.map((item) => item.id === goal.id ? { ...item, progress } : item));
              }}
              onMouseUp={(event) => {
                updateGoal(goal.id, { progress: Number((event.target as HTMLInputElement).value) }).then((next) => {
                  setGoals((current) => current.map((item) => item.id === goal.id ? next : item));
                }).catch((err: Error) => setError(err.message));
              }}
              onTouchEnd={(event) => {
                updateGoal(goal.id, { progress: Number((event.target as HTMLInputElement).value) }).then((next) => {
                  setGoals((current) => current.map((item) => item.id === goal.id ? next : item));
                }).catch((err: Error) => setError(err.message));
              }}
            />
            {goal.milestones.map((milestone) => (
              <label key={milestone.id} className="milestone">
                <input
                  type="checkbox"
                  checked={milestone.done}
                  onChange={(event) => {
                    setMilestone(goal.id, milestone.id, event.target.checked)
                      .then((next) => setGoals((current) => current.map((item) => item.id === goal.id ? next : item)))
                      .catch((err: Error) => setError(err.message));
                  }}
                />
                <span>{milestone.title} · {milestone.target_progress}%</span>
              </label>
            ))}
          </article>
        ))}
        {goals.length === 0 && <p className="muted">No goals yet. Add one, or ask the chief of staff to set one.</p>}
      </div>
    </OsShell>
  );
}
