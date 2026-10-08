/**
 * turn_completed SSE event — multi-device sync (fix 2026-10-08).
 *
 * When the session channel receives turn_completed:
 *   - A tab that is NOT processing a turn (idle) must call loadHistory().
 *   - A tab that IS processing a turn (sender) must NOT call loadHistory()
 *     (it already has the response via the per-turn SSE channel).
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useChat } from './useChat';

// ── EventSource mock ──────────────────────────────────────────────────────────

class MockEventSource {
  static instances: MockEventSource[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener() {}
  removeEventListener() {}
  close() {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Return the session SSE (url contains /events/session/). */
function getSessionES(): MockEventSource {
  const es = MockEventSource.instances.find((e) => e.url.includes('/events/session/'));
  if (!es) throw new Error('No session EventSource found');
  return es;
}

function fireTurnCompleted(turn_id = 'turn_abc') {
  const es = getSessionES();
  es.onmessage?.({ data: JSON.stringify({ type: 'turn_completed', turn_id }) });
}

function makeFetchMock(routes: Record<string, object>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase();
    const key = `${method} ${url}`;
    const body = routes[key] ?? routes[url] ?? {};
    const status = method === 'POST' && url === '/chat/message' ? 202
      : method === 'POST' ? 204 : 200;
    return { ok: true, status, json: async () => body };
  });
}

// ── Setup / teardown ──────────────────────────────────────────────────────────

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource);
  vi.stubGlobal('localStorage', {
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('useChat — turn_completed multi-device sync', () => {
  it('idle tab calls loadHistory() when turn_completed arrives', async () => {
    const fetchMock = makeFetchMock({
      'GET /chat/current': { messages: [] },
      'POST /events/visibility': {},
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    // Tab is idle (conectado) — abortControllerRef.current is null
    expect(result.current.status).toBe('conectado');

    const callsBefore = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    // Another device completed a turn — fire event on session channel
    await act(async () => { fireTurnCompleted('turn_other_device'); });

    const callsAfter = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    expect(callsAfter).toBeGreaterThan(callsBefore);
  });

  it('active (sending) tab does NOT call loadHistory() on turn_completed', async () => {
    const fetchMock = makeFetchMock({
      'GET /chat/current': { messages: [] },
      'POST /chat/message': { turn_id: 'turn_mine', status: 'queued' },
      'POST /events/visibility': {},
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    // Start a turn — abortControllerRef.current becomes non-null
    await act(async () => { void result.current.sendMessage('hola'); });
    expect(result.current.status).toBe('procesando');

    const callsBefore = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    // turn_completed arrives (same turn, from our own session channel fan-out)
    await act(async () => { fireTurnCompleted('turn_mine'); });

    const callsAfter = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    // Should NOT have triggered an extra loadHistory()
    expect(callsAfter).toBe(callsBefore);
  });
});
