import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { useNavigate } from 'react-router';
import { ArrowLeft, ArrowRight, Brain, Database, Search, ShieldCheck, Wallet } from 'lucide-react';
import { getMemoryStats, searchMemory } from '../lib/api';
import type { MemorySearchResult, MemoryStats } from '../lib/api';
import './EcosystemPage.css';

export function MemoryHubPage() {
  const navigate = useNavigate();
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [status, setStatus] = useState('Checking local memory…');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<MemorySearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');

  useEffect(() => {
    getMemoryStats().then((data) => {
      setStats(data); setStatus('Local memory available');
    }).catch(() => setStatus('Local memory unavailable'));
  }, []);

  async function onSearch(event: FormEvent) {
    event.preventDefault();
    if (!query.trim()) return;
    setSearching(true);
    setSearchError('');
    try {
      setResults(await searchMemory(query.trim(), 8));
    } catch {
      setResults(null);
      setSearchError('Could not search local memory. Check that the backend is running.');
    } finally {
      setSearching(false);
    }
  }

  return <div className="ecosystem-page"><div className="ecosystem-shell">
    <button className="ecosystem-back" onClick={() => navigate('/ecosystem')}><ArrowLeft size={16} /> Ecosystem</button>
    <header className="ecosystem-heading"><div>
      <span className="ecosystem-eyebrow"><Brain size={14} /> MEMORY ARCHITECTURE</span>
      <h1>Memory hub<span>.</span></h1>
      <p>A separate place to inspect Jarvis’s local memory and see which project memories are available.</p>
    </div></header>

    <section className="ecosystem-memory-map" aria-label="Personal and project memory">
      <div className="ecosystem-memory-hub"><span className="ecosystem-icon"><Brain size={22} /></span>
        <div><small>LOCAL MEMORY</small><h3>Assistant memory</h3>
          <p>{status}{stats ? ` · ${stats.entries} indexed entries · ${stats.backend} backend` : ''}</p></div></div>
      <div className="ecosystem-memory-branch" aria-hidden="true" />
      <div className="ecosystem-workspaces">
        <article><span className="ecosystem-icon"><Database size={19} /></span><div><small>SEPARATE DATABASE · PLANNED</small><h3>Quick Funders memory</h3><p>CRM leads and deal history would stay in its project database.</p></div><span className="ecosystem-planned">Not connected</span></article>
        <article><span className="ecosystem-icon"><Wallet size={19} /></span><div><small>SEPARATE DATABASE · PLANNED</small><h3>Self-Audit memory</h3><p>Financial records would stay in its own database.</p></div><span className="ecosystem-planned">Not connected</span></article>
      </div>
    </section>
    <div className="ecosystem-note"><ShieldCheck size={18} /><span>This search covers the indexed local memory store. Your USER.md and MEMORY.md profile files may be used by chat separately and are not guaranteed to appear in these results. Project databases are not queried or combined; they need separate read permissions and connections.</span></div>

    <div className="ecosystem-section-heading"><div><span>SEARCH LOCAL MEMORY</span><h2>Find what Jarvis remembers</h2></div></div>
    <form className="ecosystem-memory-search" onSubmit={onSearch}>
      <Search size={18} /><input aria-label="Search assistant memory" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search personal memory…" />
      <button type="submit" disabled={searching || !query.trim()}>{searching ? 'Searching…' : 'Search'} <ArrowRight size={15} /></button>
    </form>
    {searchError && <p className="ecosystem-search-error" role="alert">{searchError}</p>}
    {results && <div className="ecosystem-results" aria-live="polite">
      {results.length === 0 ? <p>No matching memories found.</p> : results.map((item, index) => <article key={index}><span>RESULT {index + 1}</span><p>{item.content}</p></article>)}
    </div>}
    <button className="ecosystem-memory-manage" onClick={() => navigate('/data-sources')}>Manage local memory and sources <ArrowRight size={16} /></button>
  </div></div>;
}
