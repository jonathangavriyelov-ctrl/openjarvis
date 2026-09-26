import { useEffect } from 'react';
import { useLocation } from 'react-router';
import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { CostComparison } from '../components/Dashboard/CostComparison';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';

export function DashboardPage() {
  const location = useLocation();
  const now = new Date();
  const stamp = now.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';

  useEffect(() => {
    const id = location.hash.replace('#', '');
    if (!id) return;
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [location.hash]);

  const jump = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6">
          <div className="flex items-center justify-between">
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
              Your Mac at a glance
            </h1>
            <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {stamp}
            </div>
          </div>
          <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
            See the electricity your Mac used, and the money you kept by not paying a cloud company.
          </p>
        </header>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 mb-6">
          <button
            type="button"
            onClick={() => jump('savings')}
            className="text-left rounded-xl p-4 cursor-pointer"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <strong className="block text-base" style={{ color: 'var(--color-text)' }}>View savings</strong>
            <span className="block text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Money saved vs. paying for cloud AI
            </span>
          </button>
          <button
            type="button"
            onClick={() => jump('energy')}
            className="text-left rounded-xl p-4 cursor-pointer"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <strong className="block text-base" style={{ color: 'var(--color-text)' }}>Check energy use</strong>
            <span className="block text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Energy used by your Mac today
            </span>
          </button>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
          <div id="energy">
            <EnergyDashboard />
          </div>
          <div id="savings">
            <CostComparison />
          </div>
        </div>

        <TraceDebugger />
      </div>
    </div>
  );
}
