import { useEffect, useState, useCallback, useRef } from 'react';
import { Routes, Route, useLocation } from 'react-router';
import { Layout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { DashboardPage } from './pages/DashboardPage';
import { EcosystemPage } from './pages/EcosystemPage';
import { MemoryHubPage } from './pages/MemoryHubPage';
import { SettingsPage } from './pages/SettingsPage';
import { GetStartedPage } from './pages/GetStartedPage';
import { AgentsPage } from './pages/AgentsPage';
import { DataSourcesPage } from './pages/DataSourcesPage';
import { LogsPage } from './pages/LogsPage';
import { WorldPage } from './pages/personal/WorldPage';
import { ChiefPage } from './pages/personal/ChiefPage';
import { AgentPage } from './pages/personal/AgentPage';
import { GoalsPage } from './pages/personal/GoalsPage';
import { SecondBrainPage } from './pages/personal/SecondBrainPage';
import { KnowledgePage } from './pages/personal/KnowledgePage';
import { DeliverablesPage } from './pages/personal/DeliverablesPage';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { useAppStore } from './lib/store';
import { fetchModels, fetchServerInfo, fetchSavings, submitSavings, isTauri } from './lib/api';
import { OptInModal } from './components/OptInModal';
import { OsLock } from './components/OsLock';
import { fetchGateStatus, LOCK_EVENT, lockDesk } from './lib/os-gate';
import { UpdateChecker } from './components/Desktop/UpdateChecker';
import { track, hashId } from './lib/analytics';

export default function App() {
  const [setupDone, setSetupDone] = useState(!isTauri());
  const handleSetupReady = useCallback(() => {
    setSetupDone(true);
    // Only fire once per install — guard against setup screen re-appearing
    // on reinstalls or dev reloads.
    if (!localStorage.getItem('oj-setup-completed')) {
      localStorage.setItem('oj-setup-completed', '1');
      track('setup_completed', { preset: 'default' });
    }
  }, []);
  const prevModelRef = useRef<string>('');
  const setModels = useAppStore((s) => s.setModels);
  const setModelsLoading = useAppStore((s) => s.setModelsLoading);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setSavings = useAppStore((s) => s.setSavings);
  const settings = useAppStore((s) => s.settings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);
  const optInEnabled = useAppStore((s) => s.optInEnabled);
  const optInDisplayName = useAppStore((s) => s.optInDisplayName);
  const optInEmail = useAppStore((s) => s.optInEmail);
  const optInAnonId = useAppStore((s) => s.optInAnonId);
  const optInModalSeen = useAppStore((s) => s.optInModalSeen);
  const optInModalOpen = useAppStore((s) => s.optInModalOpen);
  const setOptInModalOpen = useAppStore((s) => s.setOptInModalOpen);
  const markOptInModalSeen = useAppStore((s) => s.markOptInModalSeen);
  const savings = useAppStore((s) => s.savings);
  const [gate, setGate] = useState<'loading' | 'setup' | 'locked' | 'offline' | 'open'>('loading');
  const location = useLocation();
  const onPersonalDesk = location.pathname.startsWith('/os');

  useEffect(() => {
    let cancelled = false;
    fetchGateStatus()
      .then((status) => {
        if (cancelled) return;
        if (status.unlocked) setGate('open');
        else setGate(status.password_set ? 'locked' : 'setup');
      })
      .catch(() => {
        if (!cancelled) setGate('offline');
      });
    const onLock = () => {
      void lockDesk().finally(() => setGate('locked'));
    };
    window.addEventListener(LOCK_EVENT, onLock);
    return () => {
      cancelled = true;
      window.removeEventListener(LOCK_EVENT, onLock);
    };
  }, []);

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('dark', 'light');
    if (settings.theme === 'dark') root.classList.add('dark');
    else if (settings.theme === 'light') root.classList.add('light');
  }, [settings.theme]);

  // Sync overlay conversations into the main app
  const importOverlay = useAppStore((s) => s.importOverlayConversation);
  useEffect(() => {
    if (!isTauri()) return;
    importOverlay();
    const interval = setInterval(importOverlay, 5000);
    return () => clearInterval(interval);
  }, [importOverlay]);

  // Fetch models on mount
  useEffect(() => {
    if (gate !== 'open') return;
    fetchModels()
      .then((m) => {
        setModels(m);
      })
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, [gate]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch server info
  useEffect(() => {
    if (gate !== 'open') return;
    fetchServerInfo().then(setServerInfo).catch(() => {});
  }, [gate]); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll savings and optionally share to Supabase
  useEffect(() => {
    if (gate !== 'open') return;
    const refresh = () =>
      fetchSavings()
        .then((data) => {
          setSavings(data);
          if (optInEnabled && optInDisplayName && data) {
            const claudeEntry = data.per_provider.find(
              (p) => p.provider === 'claude-fable-5',
            );
            const dollarSavings = claudeEntry ? claudeEntry.total_cost : 0;
            const energySaved = data.per_provider.reduce(
              (sum, p) => sum + (p.energy_wh || 0),
              0,
            );
            const flopsSaved = data.per_provider.reduce(
              (sum, p) => sum + (p.flops || 0),
              0,
            );
            submitSavings({
              anon_id: optInAnonId,
              display_name: optInDisplayName,
              email: optInEmail,
              total_calls: data.total_calls,
              total_tokens: data.total_tokens,
              dollar_savings: dollarSavings,
              energy_wh_saved: energySaved,
              flops_saved: flopsSaved,
              token_counting_version: data.token_counting_version ?? 1,
            });
          }
        })
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, [gate, optInEnabled, optInDisplayName, optInAnonId]); // eslint-disable-line react-hooks/exhaustive-deps

  // The personal desk never auto-opens the leaderboard prompt. Elsewhere,
  // the first visit can still offer it. A settings toggle is the only way
  // to open it from /os/*.
  useEffect(() => {
    if (onPersonalDesk) {
      setOptInModalOpen(false);
      if (!optInModalSeen) markOptInModalSeen();
      return;
    }
    if (!optInModalSeen) {
      setOptInModalOpen(true);
      markOptInModalSeen();
    }
  }, [onPersonalDesk]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fire model_changed when the user switches models. First mount is
  // not a "change" — only emit when both prev and current are real and
  // differ.
  useEffect(() => {
    const prev = prevModelRef.current;
    const curr = selectedModel || '';
    prevModelRef.current = curr;
    if (!prev || !curr || prev === curr) return;
    void (async () => {
      const [fromHash, toHash] = await Promise.all([
        hashId(prev),
        hashId(curr),
      ]);
      track('model_changed', {
        from_model_hash: fromHash,
        to_model_hash: toHash,
      });
    })();
  }, [selectedModel]);

  // app_opened — one-shot per app launch, fires after analytics has had
  // a chance to initialize. platform + version are super-properties
  // registered in analytics.ts initAnalytics, so no per-call props needed.
  useEffect(() => {
    const t = setTimeout(() => {
      track('app_opened', {});
    }, 500);
    return () => clearTimeout(t);
  }, []);

  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen, toggleSystemPanel]);


  if (!setupDone) {
    return <SetupScreen onReady={handleSetupReady} />;
  }

  if (gate !== 'open') {
    if (gate === 'loading') {
      return (
        <div className="min-h-full w-full" style={{ background: 'var(--color-bg)' }} />
      );
    }
    return (
      <OsLock
        mode={gate}
        onUnlocked={() => setGate('open')}
      />
    );
  }

  return (
    <>
      <UpdateChecker />
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<ChatPage />} />
          <Route path="dashboard" element={<DashboardPage />} />
          <Route path="ecosystem" element={<EcosystemPage />} />
          <Route path="os/world" element={<WorldPage />} />
          <Route path="os/chief" element={<ChiefPage />} />
          <Route path="os/agents/:agentId" element={<AgentPage />} />
          <Route path="os/goals" element={<GoalsPage />} />
          <Route path="os/brain" element={<SecondBrainPage />} />
          <Route path="os/feed" element={<KnowledgePage />} />
          <Route path="os/library" element={<DeliverablesPage />} />
          <Route path="memory" element={<MemoryHubPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="get-started" element={<GetStartedPage />} />
          <Route path="data-sources" element={<DataSourcesPage />} />
          <Route path="agents" element={<AgentsPage />} />
          <Route path="logs" element={<LogsPage />} />
        </Route>
      </Routes>
      <Toaster position="bottom-right" />
      {commandPaletteOpen && <CommandPalette />}
      {optInModalOpen && !onPersonalDesk && (
        <OptInModal onClose={() => setOptInModalOpen(false)} />
      )}
    </>
  );
}
