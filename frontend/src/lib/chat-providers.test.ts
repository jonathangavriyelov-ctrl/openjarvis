import { describe, expect, it } from 'vitest';

import {
  attemptOrder,
  creditsError,
  fallbackNote,
  hintFor,
  modelFor,
  normalizeProvider,
} from './chat-providers';

describe('chat provider switcher', () => {
  it('defaults a new conversation to Grok', () => {
    expect(normalizeProvider('')).toBe('grok');
    expect(normalizeProvider(undefined)).toBe('grok');
    expect(modelFor('grok')).toBe('grok-4.7');
    expect(hintFor('grok')).toBe("Fast, knows what's happening now");
    expect(hintFor('claude', true)).toBe('Thinks harder');
    expect(hintFor('openai')).toBe('Backup / second opinion');
    expect(hintFor('local', true)).toBe('Free, private, and works without the internet');
  });

  it('falls back Grok, Claude, then Local and skips OpenAI', () => {
    expect(attemptOrder('grok')).toEqual(['grok', 'claude', 'local']);
    expect(attemptOrder('claude')).toEqual(['claude', 'grok', 'local']);
    expect(attemptOrder('openai')[0]).toBe('openai');
    expect(attemptOrder('grok')).not.toContain('openai');
    expect(attemptOrder('grok', { private: true })).toEqual(['local']);
    expect(attemptOrder('grok', { missingKeys: ['grok'] })).toEqual(['claude', 'local']);
    expect(attemptOrder('claude', { needsCredits: ['openai'] })).not.toContain('openai');
  });

  it('marks a credits failure and names who answered', () => {
    expect(creditsError('insufficient_quota')).toBe(true);
    expect(creditsError('credit_balance_exhausted')).toBe(true);
    expect(creditsError('network')).toBe(false);
    expect(fallbackNote('openai', 'grok', { needsCredits: true })).toBe(
      'OpenAI needs credits, so Grok answered.',
    );
    expect(fallbackNote('claude', 'local')).toBe(
      'Claude was not available, so Hermes on your Mac answered.',
    );
    expect(fallbackNote('grok', 'grok')).toBe('');
  });
});
