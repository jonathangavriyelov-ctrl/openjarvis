import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router';

const LINKS = [
  { to: '/os/world', label: 'Eco world' },
  { to: '/os/chief', label: 'Chief of Staff' },
  { to: '/os/goals', label: 'Goals' },
  { to: '/os/brain', label: 'Second Brain' },
  { to: '/os/library', label: 'Deliverables' },
];

export function OsNav() {
  const location = useLocation();
  return (
    <nav className="os-nav" aria-label="Personal AI OS">
      {LINKS.map((link) => {
        const active = location.pathname === link.to;
        return (
          <Link key={link.to} to={link.to} className={active ? 'os-nav-link is-active' : 'os-nav-link'}>
            {link.label}
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
  return (
    <div className="os-page">
      <div className="os-shell">
        <OsNav />
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
