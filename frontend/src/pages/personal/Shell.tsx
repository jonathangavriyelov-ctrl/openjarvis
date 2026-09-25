import { useEffect, useSyncExternalStore, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router';
import { fetchSettings, updateSettings } from '../../lib/personal-api';

const LINKS = [
  { to: '/os/world', label: 'Eco world', simple: 'Your world' },
  { to: '/os/chief', label: 'Chief of Staff', simple: 'The boss helper' },
  { to: '/os/goals', label: 'Goals', simple: 'Goals' },
  { to: '/os/brain', label: 'Second Brain', simple: 'Notes' },
  { to: '/os/library', label: 'Deliverables', simple: 'Finished work' },
];

let eli5Value = false;
const listeners = new Set<() => void>();

function emitEli5(next: boolean) {
  eli5Value = next;
  listeners.forEach((listener) => listener());
}

export function useEli5() {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => eli5Value,
  );
}

export function OsNav() {
  const location = useLocation();
  const eli5 = useEli5();
  return (
    <nav className="os-nav" aria-label="Personal AI OS">
      {LINKS.map((link) => {
        const active = location.pathname === link.to;
        return (
          <Link key={link.to} to={link.to} className={active ? 'os-nav-link is-active' : 'os-nav-link'}>
            {eli5 ? link.simple : link.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function OsShell({
  eyebrow,
  title,
  lede,
  action,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  const eli5 = useEli5();

  useEffect(() => {
    fetchSettings()
      .then((settings) => emitEli5(settings.eli5))
      .catch(() => {});
  }, []);

  const toggle = async () => {
    const next = !eli5;
    emitEli5(next);
    try {
      const saved = await updateSettings({ eli5: next });
      emitEli5(saved.eli5);
    } catch {
      emitEli5(!next);
    }
  };

  return (
    <div className={eli5 ? 'os-page is-eli5' : 'os-page'}>
      <div className="os-shell">
        <div className="os-nav-row">
          <OsNav />
          <button
            type="button"
            className={eli5 ? 'eli5-toggle is-on' : 'eli5-toggle'}
            onClick={toggle}
            aria-pressed={eli5}
          >
            {eli5 ? 'Simple words: on' : 'Explain like I’m 5'}
          </button>
        </div>
        <header className="os-heading">
          <div>
            <span className="os-eyebrow">{eyebrow}</span>
            <h1>{title}</h1>
            <p>{lede}</p>
          </div>
          {action}
        </header>
        {children}
      </div>
    </div>
  );
}

export function OsError({ message }: { message: string }) {
  return (
    <p className="os-banner" role="alert">
      {message}
    </p>
  );
}
