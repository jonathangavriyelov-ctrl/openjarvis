import { apiFetch } from './api';

export interface GateStatus {
  password_set: boolean;
  unlocked: boolean;
}

export const LOCK_EVENT = 'oj-os-lock';

export function requestLock(): void {
  window.dispatchEvent(new Event(LOCK_EVENT));
}

export async function fetchGateStatus(): Promise<GateStatus> {
  const response = await apiFetch('/v1/personal/auth/status');
  if (!response.ok) {
    throw new Error('The desk lock could not be read.');
  }
  return response.json() as Promise<GateStatus>;
}

async function sendPassword(path: string, password: string): Promise<string | null> {
  const response = await apiFetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  });
  if (response.ok) return null;
  let detail = 'That did not work.';
  try {
    const body = await response.json();
    if (typeof body?.detail === 'string') detail = body.detail;
  } catch {
    /* not JSON */
  }
  return detail;
}

export function createPassword(password: string): Promise<string | null> {
  return sendPassword('/v1/personal/auth/setup', password);
}

export function unlockPassword(password: string): Promise<string | null> {
  return sendPassword('/v1/personal/auth/login', password);
}

export async function lockDesk(): Promise<void> {
  await apiFetch('/v1/personal/auth/lock', { method: 'POST' });
}
