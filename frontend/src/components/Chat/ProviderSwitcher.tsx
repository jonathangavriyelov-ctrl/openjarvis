import { useEffect, useRef, useState } from 'react';
import './ProviderSwitcher.css';
import { useAppStore } from '../../lib/store';
import { apiFetch } from '../../lib/api';
import {
  CHAT_PROVIDERS,
  hintFor,
  labelFor,
  normalizeProvider,
  type ChatProviderId,
} from '../../lib/chat-providers';

export function ProviderSwitcher({
  eli5 = false,
  value,
  onChange,
}: {
  eli5?: boolean;
  value?: ChatProviderId;
  onChange?: (id: ChatProviderId) => void;
}) {
  const activeId = useAppStore((s) => s.activeId);
  const conversations = useAppStore((s) => s.conversations);
  const draftProvider = useAppStore((s) => s.draftProvider);
  const setDraftProvider = useAppStore((s) => s.setDraftProvider);
  const setConversationProvider = useAppStore((s) => s.setConversationProvider);
  const needsCredits = useAppStore((s) => s.openaiNeedsCredits);
  const setOpenaiNeedsCredits = useAppStore((s) => s.setOpenaiNeedsCredits);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const conversation = conversations.find((item) => item.id === activeId);
  const current = normalizeProvider(value || conversation?.provider || draftProvider);

  useEffect(() => {
    let cancelled = false;
    apiFetch('/v1/personal/providers')
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.providers) return;
        const openai = data.providers.find((item: { id?: string }) => item.id === 'openai');
        if (openai?.needs_credits) setOpenaiNeedsCredits(true);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [setOpenaiNeedsCredits]);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [open]);

  const choose = (id: ChatProviderId) => {
    if (onChange) onChange(id);
    else if (activeId) setConversationProvider(activeId, id);
    else setDraftProvider(id);
    setOpen(false);
  };

  return (
    <div className="provider-switch" ref={rootRef}>
      <button
        type="button"
        className="provider-pill"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span>{labelFor(current, eli5)}</span>
        <em>{needsCredits && current === 'openai' ? 'Needs credits' : hintFor(current, eli5)}</em>
      </button>
      {open && (
        <ul className="provider-menu" role="listbox" aria-label="Who answers">
          {CHAT_PROVIDERS.map((option) => {
            const credits = option.id === 'openai' && needsCredits;
            return (
              <li key={option.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={option.id === current}
                  className={option.id === current ? 'is-current' : ''}
                  onClick={() => choose(option.id)}
                >
                  <strong>
                    {labelFor(option.id, eli5)}
                    {credits ? <span className="provider-credits">Needs credits</span> : null}
                  </strong>
                  <span>{hintFor(option.id, eli5)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
