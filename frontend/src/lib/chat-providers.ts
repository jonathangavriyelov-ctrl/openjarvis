/** Plain labels for the per-conversation model switcher. */

export type ChatProviderId = 'grok' | 'claude' | 'openai' | 'local';

export interface ChatProviderOption {
  id: ChatProviderId;
  label: string;
  hint: string;
  eli5: string;
  model: string;
}

export const CHAT_PROVIDERS: ChatProviderOption[] = [
  {
    id: 'grok',
    label: 'Grok',
    hint: "Fast, knows what's happening now",
    eli5: 'Quick, and it knows what is new',
    model: 'grok-4.7',
  },
  {
    id: 'claude',
    label: 'Claude',
    hint: 'Deeper thinking and analysis',
    eli5: 'Thinks harder',
    model: 'claude-opus-5-5',
  },
  {
    id: 'openai',
    label: 'OpenAI',
    hint: 'Backup / second opinion',
    eli5: 'A second opinion',
    model: 'gpt-6-sol',
  },
  {
    id: 'local',
    label: 'Local',
    hint: 'Free and private, works offline',
    eli5: 'Free, private, and works without the internet',
    model: 'hermes3:8b',
  },
];

const FALLBACK: ChatProviderId[] = ['grok', 'claude', 'local'];

export function normalizeProvider(value?: string | null): ChatProviderId {
  const text = (value || '').trim().toLowerCase();
  if (text === 'xai') return 'grok';
  if (text === 'anthropic') return 'claude';
  if (text === 'gpt') return 'openai';
  if (text === 'hermes') return 'local';
  if (CHAT_PROVIDERS.some((item) => item.id === text)) return text as ChatProviderId;
  return 'grok';
}

export function providerOption(id: string): ChatProviderOption {
  const chosen = normalizeProvider(id);
  return CHAT_PROVIDERS.find((item) => item.id === chosen) || CHAT_PROVIDERS[0];
}

export function modelFor(id: string): string {
  return providerOption(id).model;
}

export function labelFor(id: string, eli5 = false): string {
  if (eli5 && normalizeProvider(id) === 'local') return 'On this Mac';
  return providerOption(id).label;
}

export function hintFor(id: string, eli5 = false): string {
  const option = providerOption(id);
  return eli5 ? option.eli5 : option.hint;
}

export function creditsError(text: string): boolean {
  const lowered = (text || '').toLowerCase();
  return lowered.includes('insufficient_quota') || lowered.includes('credit_balance_exhausted');
}

export function attemptOrder(
  choice: string,
  options?: { private?: boolean; missingKeys?: ChatProviderId[]; needsCredits?: ChatProviderId[] },
): ChatProviderId[] {
  if (options?.private) return ['local'];
  const requested = normalizeProvider(choice);
  const missing = new Set(options?.missingKeys || []);
  const credits = new Set(options?.needsCredits || []);
  const chain = [requested, ...FALLBACK.filter((item) => item !== requested)];
  const ready: ChatProviderId[] = [];
  chain.forEach((item, index) => {
    if (item !== 'local' && missing.has(item)) return;
    if (credits.has(item) && index !== 0) return;
    ready.push(item);
  });
  if (!ready.includes('local')) ready.push('local');
  return ready;
}

export function fallbackNote(
  requested: string,
  answered: string,
  options?: { needsCredits?: boolean; eli5?: boolean },
): string {
  const asked = normalizeProvider(requested);
  const used = answered ? normalizeProvider(answered) : '';
  if (!used || asked === used) return '';
  const who = used === 'local'
    ? (options?.eli5 ? 'the helper on this Mac' : 'Hermes on your Mac')
    : labelFor(used, options?.eli5);
  if (options?.needsCredits && asked === 'openai') {
    return `OpenAI needs credits, so ${who} answered.`;
  }
  return `${labelFor(asked, options?.eli5)} was not available, so ${who} answered.`;
}

export function readStoredProvider(key: string): ChatProviderId {
  try {
    return normalizeProvider(localStorage.getItem(key));
  } catch {
    return 'grok';
  }
}

export function writeStoredProvider(key: string, provider: string): void {
  try {
    localStorage.setItem(key, normalizeProvider(provider));
  } catch {
    /* private mode */
  }
}
