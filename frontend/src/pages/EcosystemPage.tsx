import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import {
  Activity, ArrowRight, Bot, Brain, Check, CircleHelp, Cpu, Database,
  Flower2, HardDrive, Layers3, Mic2, PlugZap, RefreshCw, ShieldCheck, Wallet,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { checkHealth, fetchManagedAgents, fetchSpeechHealth, getMemoryStats } from '../lib/api';
import { listConnectors } from '../lib/connectors-api';
import { useAppStore } from '../lib/store';
import './EcosystemPage.css';

type Availability = 'checking' | 'ready' | 'unavailable' | 'planned';

interface Module {
  title: string;
  description: string;
  icon: LucideIcon;
  state: Availability;
  detail: string;
  destination?: string;
}

function Status({ state, detail }: { state: Availability; detail: string }) {
  return <span className={`ecosystem-status ecosystem-status--${state}`}>
    <span className="ecosystem-status-dot" />{detail}
  </span>;
}

function ModuleCard({ module, onNavigate }: { module: Module; onNavigate: (path: string) => void }) {
  const Icon = module.icon;
  return <article className="ecosystem-module">
    <div className="ecosystem-module-top">
      <span className="ecosystem-icon"><Icon size={19} strokeWidth={1.8} /></span>
      <Status state={module.state} detail={module.detail} />
    </div>
    <h3>{module.title}</h3>
    <p>{module.description}</p>
    {module.destination && <button className="ecosystem-link" onClick={() => onNavigate(module.destination!)}>
      Open {module.title} <ArrowRight size={15} />
    </button>}
  </article>;
}

export function EcosystemPage() {
  const navigate = useNavigate();
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const [server, setServer] = useState<Availability>('checking');
  const [voice, setVoice] = useState<Availability>('checking');
  const [memory, setMemory] = useState<Availability>('checking');
  const [memoryEntries, setMemoryEntries] = useState<number | null>(null);
  const [agentCount, setAgentCount] = useState<number | null>(null);
  const [connectorCount, setConnectorCount] = useState<number | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const refresh = useCallback(async () => {
    const online = await checkHealth().catch(() => false);
    setServer(online ? 'ready' : 'unavailable');
    if (!online) {
      setVoice('unavailable'); setMemory('unavailable');
      setMemoryEntries(null); setAgentCount(null); setConnectorCount(null);
      setUpdatedAt(new Date());
      return;
    }
    const [speech, stats, agents, connectors] = await Promise.allSettled([
      fetchSpeechHealth(), getMemoryStats(), fetchManagedAgents(), listConnectors(),
    ]);
    setVoice(speech.status === 'fulfilled' && speech.value.available ? 'ready' : 'unavailable');
    setMemory(stats.status === 'fulfilled' ? 'ready' : 'unavailable');
    setMemoryEntries(stats.status === 'fulfilled' ? stats.value.entries : null);
    setAgentCount(agents.status === 'fulfilled' ? agents.value.length : null);
    setConnectorCount(connectors.status === 'fulfilled'
      ? connectors.value.filter((connector) => connector.connected).length : null);
    setUpdatedAt(new Date());
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { void refresh(); }, 30000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const modelLabel = selectedModel || serverInfo?.model || 'No model reported';
  const modules: Module[] = [
    {
      title: 'Conversation', icon: Mic2, state: voice,
      detail: voice === 'ready' ? 'Speech input ready' : voice === 'checking' ? 'Checking' : 'Speech input unavailable',
      description: 'Talk or type with Jarvis. Speech input status comes from the local server.',
      destination: '/',
    },
    {
      title: 'Local intelligence', icon: Cpu, state: server,
      detail: server === 'ready' ? 'Server reachable' : server === 'checking' ? 'Checking' : 'Server offline',
      description: `Current model: ${modelLabel}. Answers and agent actions run through the configured engine.`,
      destination: '/settings',
    },
    {
      title: 'Personal memory', icon: Brain, state: memory,
      detail: memory === 'ready' ? `${memoryEntries ?? 0} indexed entries` : memory === 'checking' ? 'Checking' : 'Memory status unavailable',
      description: 'Your assistant-wide memory lives here. Project databases remain separate.',
      destination: '/memory',
    },
    {
      title: 'Agents & connections', icon: Bot,
      state: agentCount === null ? 'unavailable' : 'ready',
      detail: agentCount === null ? 'Status unavailable' : `${agentCount} agents`,
      description: `${connectorCount === null ? 'Connection status unavailable' : `${connectorCount} connected sources`}. Manage real agents and connected data in their own pages.`,
      destination: '/agents',
    },
  ];

  return <div className="ecosystem-page">
    <div className="ecosystem-shell">
      <header className="ecosystem-heading">
        <div>
          <span className="ecosystem-eyebrow"><Activity size={14} /> YOUR ASSISTANT SYSTEM</span>
          <h1>Jarvis ecosystem<span>.</span></h1>
          <p>A clear view of what powers your assistant, what it remembers, and how your projects fit together.</p>
        </div>
        <button className="ecosystem-refresh" onClick={() => { void refresh(); }} aria-label="Refresh system status">
          <RefreshCw size={16} /> Refresh
        </button>
      </header>

      <section className="ecosystem-hero" aria-label="Assistant architecture">
        <div className="ecosystem-hero-copy">
          <span className="ecosystem-hero-kicker">YOUR LOCAL COMMAND CENTER</span>
          <h2>One assistant.<br /><em>Connected workspaces.</em></h2>
          <p>Speak with Jarvis, keep your personal context in one place, and give each project its own dedicated memory and tools.</p>
          <button onClick={() => navigate('/')} className="ecosystem-primary">Talk to Jarvis <ArrowRight size={17} /></button>
        </div>
        <div className="ecosystem-orbit" aria-hidden="true">
          <span className="ecosystem-orbit-ring ecosystem-orbit-ring-one" />
          <span className="ecosystem-orbit-ring ecosystem-orbit-ring-two" />
          <span className="ecosystem-orbit-core">J<span>✦</span></span>
          <span className="ecosystem-orbit-node ecosystem-orbit-node-voice"><Mic2 size={17} /> Voice</span>
          <span className="ecosystem-orbit-node ecosystem-orbit-node-memory"><Brain size={17} /> Memory</span>
          <span className="ecosystem-orbit-node ecosystem-orbit-node-work"><Layers3 size={17} /> Projects</span>
        </div>
      </section>

      <div className="ecosystem-section-heading"><div><span>01 / THE FOUNDATION</span><h2>What is running</h2></div>
        <span className="ecosystem-updated">{updatedAt ? `Checked ${updatedAt.toLocaleTimeString()}` : 'Checking status…'}</span>
      </div>
      <section className="ecosystem-modules" aria-label="Assistant modules">
        {modules.map((module) => <ModuleCard key={module.title} module={module} onNavigate={navigate} />)}
      </section>

      <div className="ecosystem-section-heading"><div><span>02 / MEMORY ARCHITECTURE</span><h2>One personal hub. Separate project memory.</h2></div></div>
      <section className="ecosystem-memory-map" aria-label="Memory spaces">
        <div className="ecosystem-memory-hub">
          <span className="ecosystem-icon"><Brain size={22} /></span>
          <div><small>ASSISTANT-WIDE</small><h3>Personal memory hub</h3>
            <p>Your preferences, priorities, and cross-project context. Jarvis can use this to understand you across conversations.</p></div>
          <button className="ecosystem-hub-action" onClick={() => navigate('/memory')}>Open memory hub <ArrowRight size={15} /></button>
        </div>
        <div className="ecosystem-memory-branch" aria-hidden="true" />
        <div className="ecosystem-workspaces">
          <article><span className="ecosystem-icon"><HardDrive size={19} /></span><div><small>PROJECT SPACE · PLANNED</small><h3>Quick Funders</h3><p>CRM records, lead notes, pipeline activity, and its own project memory.</p></div><span className="ecosystem-planned">Not connected</span></article>
          <article><span className="ecosystem-icon"><Wallet size={19} /></span><div><small>PROJECT SPACE · PLANNED</small><h3>Self-Audit</h3><p>Bank and card records, statements, reconciliations, and its own project memory.</p></div><span className="ecosystem-planned">Not connected</span></article>
        </div>
      </section>
      <div className="ecosystem-note"><ShieldCheck size={18} /><span>Project memories are shown as separate spaces. Cross-project access and database links require explicit integration before Jarvis can use them.</span></div>

      <div className="ecosystem-section-heading"><div><span>03 / BUILD OUT</span><h2>Grow the ecosystem</h2></div></div>
      <section className="ecosystem-next">
        <button onClick={() => navigate('/data-sources')}><Database size={20} /><span><strong>Connect data</strong><small>Review actual connected sources and local memory.</small></span><ArrowRight size={17} /></button>
        <button onClick={() => navigate('/agents')}><PlugZap size={20} /><span><strong>Set up agents</strong><small>Assign focused work to each assistant.</small></span><ArrowRight size={17} /></button>
        <button onClick={() => navigate('/os/world')}><Flower2 size={20} /><span><strong>Open the eco world</strong><small>See the chief of staff and the specialist team.</small></span><ArrowRight size={17} /></button>
        <button onClick={() => navigate('/get-started')}><CircleHelp size={20} /><span><strong>Explore setup</strong><small>See the app’s available setup steps.</small></span><ArrowRight size={17} /></button>
      </section>
      <div className="ecosystem-footer"><Check size={15} /> Live badges reflect server responses. Planned workspaces are examples, not active integrations.</div>
    </div>
  </div>;
}
