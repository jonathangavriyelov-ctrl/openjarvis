import { useState, useEffect, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Zap, Activity, Thermometer, Hash, Gauge } from 'lucide-react';
import { fetchEnergy, fetchTelemetry } from '../../lib/api';
import { useAppStore } from '../../lib/store';
import { HelpTip } from '../HelpTip';

interface EnergySample {
  timestamp: string;
  power_w: number;
  energy_j: number;
}

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  samples?: EnergySample[];
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

interface ChartPoint {
  time: string;
  power: number;
}

function StatCard({
  icon: Icon,
  label,
  value,
  unit,
  hint,
  tip,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
  unit?: string;
  hint: string;
  tip: string;
}) {
  return (
    <div className="hud-panel p-4" style={{ overflow: 'visible' }}>
      <div className="flex items-center gap-2 mb-2">
        <Icon size={12} style={{ color: 'var(--color-accent)' }} />
        <span className="text-xs font-medium" style={{ color: 'var(--color-text-secondary)' }}>{label}</span>
        <HelpTip above text={tip} />
      </div>
      <div className="text-2xl font-semibold truncate" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="text-sm font-medium ml-1" style={{ color: 'var(--color-text-secondary)' }}>
            {unit}
          </span>
        )}
      </div>
      <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{hint}</p>
    </div>
  );
}

export function EnergyDashboard() {
  const savings = useAppStore((s) => s.savings);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [energyRes, telRes] = await Promise.allSettled([
        fetchEnergy().catch(() => null),
        fetchTelemetry().catch(() => null),
      ]);

      if (energyRes.status === 'fulfilled' && energyRes.value) {
        const data = energyRes.value as EnergyData;
        setEnergy(data);
        if (data.samples) {
          setChartData(
            data.samples.map((s) => ({
              time: new Date(s.timestamp).toLocaleTimeString(),
              power: Math.round(s.power_w * 10) / 10,
            })),
          );
        }
        setError(null);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
    } catch {
      setError('Cannot connect to server');
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const thermalStatus = (energy?.avg_power_w ?? 0) < 50
    ? { label: 'Cool', color: 'var(--color-success)' }
    : (energy?.avg_power_w ?? 0) < 150
    ? { label: 'Warm', color: 'var(--color-warning)' }
    : { label: 'Hot', color: 'var(--color-error)' };

  if (error || !energy) {
    return (
      <div className="hud-panel p-6" style={{ overflow: 'visible' }}>
        <h3 className="text-sm font-semibold flex items-center gap-2 mb-1" style={{ color: 'var(--color-text)' }}>
          <Zap size={14} style={{ color: 'var(--color-accent)' }} />
          Energy used by your Mac today
          <HelpTip above text="Kilojoules and joules measure electricity. Watts are how fast your Mac is using it right now." />
        </h3>
        <p className="text-xs mb-4" style={{ color: 'var(--color-text-secondary)' }}>
          This is the electricity your computer used while answering.
        </p>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span>{error || 'No energy numbers yet. Ask something on this Mac and they will show up here.'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="hud-panel p-6" style={{ overflow: 'visible' }}>
      <h3 className="text-sm font-semibold flex items-center gap-2 mb-1" style={{ color: 'var(--color-text)' }}>
        <Zap size={14} style={{ color: 'var(--color-accent)' }} />
        Energy used by your Mac today
        <HelpTip above text="Kilojoules and joules measure electricity. Watts are how fast your Mac is using it right now." />
      </h3>
      <p className="text-xs mb-4" style={{ color: 'var(--color-text-secondary)' }}>
        This is the electricity your computer used while answering.
      </p>

      <div className="grid grid-cols-2 gap-3 mb-4">
        <StatCard
          icon={Zap}
          label="Energy used"
          value={((energy.total_energy_j ?? 0) / 1000).toFixed(1)}
          unit="kilojoules"
          hint="All the electricity counted so far."
          tip="A kilojoule is a measure of energy. This is the total your Mac has used for answers."
        />
        <StatCard
          icon={Activity}
          label="Energy per token"
          value={(energy.energy_per_token_j ?? 0).toFixed(3)}
          unit="joules"
          hint="A token is a small piece of a word."
          tip="Each token is a small piece of text. This is the energy for one of those pieces."
        />
        <StatCard
          icon={Thermometer}
          label="Power right now"
          value={(energy.avg_power_w ?? 0).toFixed(1)}
          unit="watts"
          hint="How hard your Mac is working this moment."
          tip="Watts are how fast the computer is using electricity right now."
        />
        <StatCard
          icon={Hash}
          label="Questions asked"
          value={String(savings?.total_calls ?? telemetry?.total_requests ?? 0)}
          hint="How many times you asked for an answer."
          tip="Each question you send counts as one request."
        />
        <StatCard
          icon={Gauge}
          label="How warm it is"
          value={thermalStatus.label}
          hint="Cool means the computer is comfortable."
          tip="Cool, warm, or hot describes how hard the machine is working, not the room temperature."
        />
        <StatCard
          icon={Hash}
          label="Text handled"
          value={formatNumber(savings?.total_tokens ?? telemetry?.total_tokens ?? 0)}
          unit="tokens"
          hint="Tokens are the small pieces of text read and written."
          tip="The model reads and writes text in small pieces called tokens."
        />
      </div>

      {/* Chart */}
      {chartData.length > 1 && (
        <div className="h-48">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
              <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} />
              <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} unit="W" />
              <Tooltip
                contentStyle={{
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius-md)',
                  fontSize: 12,
                  color: 'var(--color-text)',
                }}
              />
              <Line type="monotone" dataKey="power" stroke="var(--color-accent)" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
