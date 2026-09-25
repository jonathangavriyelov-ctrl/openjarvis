import { apiFetch } from './api';

export type AgentStatus = 'idle' | 'working' | 'done';
export type Pace = 'on_track' | 'at_risk' | 'behind' | 'complete';

export interface ModelChoice {
  model_id: string;
  source: 'hermes' | 'fallback' | 'offline' | string;
  detail: string;
}

export interface PersonalAgent {
  id: string;
  name: string;
  title: string;
  description: string;
  niche: string;
  accent: string;
  skills: string[];
  prefers_hermes: boolean;
  status: AgentStatus;
  current_work: string;
  model: ModelChoice | null;
  tasks?: PersonalTask[];
  deliverables?: Deliverable[];
  skills_detail?: { name: string; description: string }[];
}

export interface DelegationEdge {
  from: string;
  to: string;
  status: string;
  title: string;
  task_id: string;
}

export interface Mission {
  id: string;
  request: string;
  status: string;
  summary: string;
  plan: { specialist_id: string; title: string; brief: string }[];
  workflow: {
    name?: string;
    success?: boolean;
    nodes?: { id: string; type: string; agent: string }[];
    edges?: { source: string; target: string }[];
  };
  model: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  tasks?: PersonalTask[];
  deliverables?: Deliverable[];
}

export interface PersonalTask {
  id: string;
  mission_id: string;
  specialist_id: string;
  title: string;
  brief: string;
  status: string;
  output: string;
  a2a?: { id?: string; state?: string; input?: string; output?: string };
}

export interface Deliverable {
  id: string;
  mission_id: string;
  task_id: string;
  specialist_id: string;
  title: string;
  kind: string;
  body: string;
  model_id: string;
  model_source: string;
  created_at: string;
}

export interface Milestone {
  id: string;
  title: string;
  target_progress: number;
  done: boolean;
}

export interface Goal {
  id: string;
  title: string;
  target: string;
  deadline: string | null;
  progress: number;
  notes: string;
  on_track: Pace;
  pace: string;
  milestones: Milestone[];
  created_at: string;
  updated_at: string;
}

export interface Note {
  id: string;
  title: string;
  body: string;
  tags: string;
  source: string;
  memory_id: string;
  created_at: string;
}

export interface WorldSnapshot {
  agents: PersonalAgent[];
  edges: DelegationEdge[];
  mission: Mission | null;
  hermes: ModelChoice;
}

async function read<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
    ...((init?.headers as Record<string, string> | undefined) ?? {}),
  };
  const response = await apiFetch(path, { ...init, headers });
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (typeof body?.detail === 'string') detail = body.detail;
    } catch {
      /* the body was not JSON */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const fetchWorld = () => read<WorldSnapshot>('/v1/personal/world');

export const fetchAgent = (id: string) => read<PersonalAgent>(`/v1/personal/agents/${id}`);

export const fetchHermes = () =>
  read<{
    executive_assistant: ModelChoice;
    configured: ModelChoice;
    hermes_model: string;
  }>('/v1/personal/hermes');

export const submitMission = (request: string) =>
  read<Mission>('/v1/personal/missions', {
    method: 'POST',
    body: JSON.stringify({ request }),
  });

export const fetchMission = (id: string) => read<Mission>(`/v1/personal/missions/${id}`);

export const fetchMissions = () => read<{ missions: Mission[] }>('/v1/personal/missions');

export const runCheckin = () => read<Mission>('/v1/personal/checkin', { method: 'POST' });

export const fetchGoals = () =>
  read<{ goals: Goal[]; checkins: { id: string; prompt: string; goal_id: string | null }[] }>(
    '/v1/personal/goals',
  );

export const createGoal = (goal: {
  title: string;
  target: string;
  deadline?: string | null;
  progress?: number;
}) =>
  read<Goal>('/v1/personal/goals', {
    method: 'POST',
    body: JSON.stringify(goal),
  });

export const updateGoal = (id: string, patch: { progress?: number; title?: string; target?: string; deadline?: string | null }) =>
  read<Goal>(`/v1/personal/goals/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const setMilestone = (goalId: string, milestoneId: string, done: boolean) =>
  read<Goal>(`/v1/personal/goals/${goalId}/milestones/${milestoneId}`, {
    method: 'POST',
    body: JSON.stringify({ done }),
  });

export const fetchDeliverables = (specialistId = '') =>
  read<{ deliverables: Deliverable[] }>(
    `/v1/personal/deliverables${specialistId ? `?specialist_id=${encodeURIComponent(specialistId)}` : ''}`,
  );

export const fetchNotes = () => read<{ notes: Note[] }>('/v1/personal/notes');

export const captureNote = (note: { title: string; body: string; tags?: string }) =>
  read<Note>('/v1/personal/notes', {
    method: 'POST',
    body: JSON.stringify(note),
  });

export const askBrain = (question: string) =>
  read<{ answer: string; hits: string[]; model: ModelChoice }>('/v1/personal/notes/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
  });

export function statusLabel(status: string): string {
  if (status === 'working' || status === 'running') return 'Working';
  if (status === 'done' || status === 'completed') return 'Done';
  if (status === 'failed') return 'Stopped';
  if (status === 'pending' || status === 'planning') return 'Queued';
  return 'Idle';
}
