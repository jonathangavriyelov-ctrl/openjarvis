import { apiFetch } from './api';

export type AgentStatus = 'idle' | 'working' | 'done';
export type Pace = 'on_track' | 'at_risk' | 'behind' | 'complete';

export interface ModelChoice {
  model_id: string;
  source: 'hermes' | 'fallback' | 'offline' | 'omniroute' | string;
  detail: string;
  route?: 'engine' | 'omniroute' | 'offline' | string;
}

export interface OmniRouteStatus {
  configured: boolean;
  reachable: boolean;
  base_url: string;
  default_model?: string;
  models?: string[];
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
  command?: string;
  project_id?: string | null;
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

export interface MediaAsset {
  id: string;
  kind: string;
  status: string;
  url: string;
  detail: string;
  prompt: string;
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
  media?: MediaAsset[];
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
  project_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectPlot {
  id: string;
  name: string;
  summary: string;
  accent: string;
  example: boolean;
  goals: Goal[];
  tasks: PersonalTask[];
}

export interface WorkLink {
  from: string;
  to: string;
  status: string;
  title: string;
}

export interface DeskCommand {
  name: string;
  title: string;
  summary: string;
  mode: string;
  specialists: string[];
  persona: string;
  source: string;
}

export interface GoogleStatus {
  connected: boolean;
  gmail: boolean;
  calendar: boolean;
  drive: boolean;
  detail: string;
}

export interface PhoneChannelStatus {
  ready: boolean;
  restricted: boolean;
  listening: boolean;
  detail: string;
}

export interface PhoneStatus {
  telegram: PhoneChannelStatus;
  slack: PhoneChannelStatus;
}

export interface Briefing {
  connected: boolean;
  inbox: { from: string; subject: string; snippet: string }[];
  meetings: { title: string; when: string }[];
  text: string;
  google: GoogleStatus;
}

export interface Proposal {
  id: string;
  kind: string;
  title: string;
  payload: {
    to?: string;
    subject?: string;
    body?: string;
    summary?: string;
    description?: string;
  };
  status: string;
  detail: string;
  mission_id: string;
  created_at: string;
}

export interface DeskSettings {
  eli5: boolean;
  higgsfield: { configured: boolean; image_model: string; video_model: string };
  commands: DeskCommand[];
  google?: GoogleStatus;
  phone?: PhoneStatus;
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
  works?: WorkLink[];
  projects?: ProjectPlot[];
  mission: Mission | null;
  hermes: ModelChoice;
  eli5?: boolean;
  higgsfield?: DeskSettings['higgsfield'];
  omniroute?: OmniRouteStatus;
  google?: GoogleStatus;
  phone?: PhoneStatus;
  commands?: DeskCommand[];
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

export const fetchSettings = () => read<DeskSettings>('/v1/personal/settings');

export const updateSettings = (patch: { eli5?: boolean }) =>
  read<DeskSettings>('/v1/personal/settings', {
    method: 'PUT',
    body: JSON.stringify(patch),
  });

export const fetchProjects = () => read<{ projects: ProjectPlot[] }>('/v1/personal/projects');

export const createProject = (project: { name: string; summary?: string; accent?: string }) =>
  read<ProjectPlot>('/v1/personal/projects', {
    method: 'POST',
    body: JSON.stringify(project),
  });

export const updateProject = (id: string, patch: { name?: string; summary?: string }) =>
  read<ProjectPlot>(`/v1/personal/projects/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const deleteProject = (id: string) =>
  read<{ deleted: boolean }>(`/v1/personal/projects/${id}`, { method: 'DELETE' });

export const createGoal = (goal: {
  title: string;
  target: string;
  deadline?: string | null;
  progress?: number;
  project_id?: string | null;
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

export const fetchBriefing = () => read<Briefing>('/v1/personal/briefing');

export const fetchProposals = () => read<{ proposals: Proposal[] }>('/v1/personal/proposals');

export const approveProposal = (id: string) =>
  read<Proposal>(`/v1/personal/proposals/${id}/approve`, { method: 'POST' });

export const rejectProposal = (id: string) =>
  read<Proposal>(`/v1/personal/proposals/${id}/reject`, { method: 'POST' });

export const fetchPhone = () => read<PhoneStatus>('/v1/personal/phone');

export const pullDrive = (query: string) =>
  read<{ connected: boolean; files: { name: string; link: string }[]; notes: Note[] }>(
    '/v1/personal/drive/pull',
    { method: 'POST', body: JSON.stringify({ query }) },
  );

export function routeLabel(model: ModelChoice | null | undefined): string {
  if (!model || model.source === 'offline' || !model.model_id) return 'Local notes';
  const name = model.model_id;
  if (model.route === 'omniroute' || model.source === 'omniroute') return `OmniRoute · ${name}`;
  if (model.source === 'hermes') return `Hermes · ${name}`;
  return `Engine · ${name}`;
}

export function statusLabel(status: string, eli5 = false): string {
  if (status === 'working' || status === 'running') return eli5 ? 'Busy' : 'Working';
  if (status === 'done' || status === 'completed') return eli5 ? 'Finished' : 'Done';
  if (status === 'failed') return eli5 ? 'Stopped' : 'Stopped';
  if (status === 'pending' || status === 'planning') return eli5 ? 'Waiting' : 'Queued';
  return eli5 ? 'Resting' : 'Idle';
}
