import { useState, type FormEvent } from 'react';
import { createPassword, unlockPassword } from '../lib/os-gate';

export function OsLock({
  mode,
  onUnlocked,
}: {
  mode: 'setup' | 'locked' | 'offline';
  onUnlocked: () => void;
}) {
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const creating = mode === 'setup';

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (mode === 'offline') return;
    if (creating && password !== confirm) {
      setError('Those passwords do not match.');
      return;
    }
    setBusy(true);
    setError('');
    const detail = creating
      ? await createPassword(password)
      : await unlockPassword(password);
    setBusy(false);
    if (detail) {
      setError(detail);
      return;
    }
    setPassword('');
    setConfirm('');
    onUnlocked();
  };

  const title = creating ? 'Create your password' : mode === 'offline' ? 'Desk unreachable' : 'Unlock';
  const lede = creating
    ? 'The desk stays blank until this password is set. Only a hash is stored on this Mac.'
    : mode === 'offline'
      ? 'The API is not answering, so nothing from the desk is shown.'
      : 'Worlds, pages, and saved data stay hidden until you unlock.';

  return (
    <div
      className="min-h-full w-full flex items-center justify-center px-6"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text)' }}
    >
      <form
        onSubmit={submit}
        className="w-full max-w-md rounded-2xl p-8"
        style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
      >
        <p className="text-xs font-semibold tracking-wide uppercase mb-3" style={{ color: 'var(--color-accent)' }}>
          Personal AI OS
        </p>
        <h1 className="text-2xl font-semibold mb-2">{title}</h1>
        <p className="text-sm mb-6" style={{ color: 'var(--color-text-secondary)' }}>
          {lede}
        </p>
        {mode !== 'offline' && (
          <>
            <label className="block text-sm mb-4">
              Password
              <input
                type="password"
                name="password"
                autoComplete={creating ? 'new-password' : 'current-password'}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1 w-full rounded-lg px-3 py-2 text-sm"
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
                minLength={8}
                required
              />
            </label>
            {creating && (
              <label className="block text-sm mb-4">
                Confirm password
                <input
                  type="password"
                  name="confirm"
                  autoComplete="new-password"
                  value={confirm}
                  onChange={(event) => setConfirm(event.target.value)}
                  className="mt-1 w-full rounded-lg px-3 py-2 text-sm"
                  style={{
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text)',
                  }}
                  minLength={8}
                  required
                />
              </label>
            )}
            {error && (
              <p className="text-sm mb-4" role="alert" style={{ color: 'var(--color-error)' }}>
                {error}
              </p>
            )}
            <button
              type="submit"
              disabled={busy}
              className="w-full rounded-lg py-2 text-sm font-medium cursor-pointer"
              style={{ background: 'var(--color-accent)', color: 'white' }}
            >
              {busy ? 'Checking…' : creating ? 'Create password' : 'Unlock'}
            </button>
          </>
        )}
      </form>
    </div>
  );
}
