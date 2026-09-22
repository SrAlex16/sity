/**
 * R10-02 regression: visibilitychange handler must reconcile chat state
 * when the tab returns to foreground during an active turn, without
 * prematurely clearing the "procesando" indicator.
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
  private _listeners: Map<string, ((e: Event) => void)[]> = new Map();

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, handler: (e: Event) => void) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type)!.push(handler);
  }

  removeEventListener() {}
  close() {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function setVisibilityState(value: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', {
    value,
    configurable: true,
    writable: true,
  });
}

function fireVisibilityChange() {
  document.dispatchEvent(new Event('visibilitychange'));
}

/** Build a stub fetch that dispatches by URL. */
function makeFetchMock(routes: Record<string, object>) {
  return vi.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase();
    const key = `${method} ${url}`;
    const body = routes[key] ?? routes[url] ?? {};
    return {
      ok: true,
      status: method === 'POST' ? 202 : 200,
      json: async () => body,
    };
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
  setVisibilityState('visible');
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('useChat — visibility reconciliation (R10-02)', () => {
  it('calls /chat/current when tab returns while procesando', async () => {
    const fetchMock = makeFetchMock({
      'GET /chat/current': { messages: [] },
      'POST /chat/message': { turn_id: 'turn_vis_001', status: 'queued' },
      'POST /events/visibility': {},
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    // Trigger sendMessage → status becomes 'procesando'
    await act(async () => { void result.current.sendMessage('hola'); });
    expect(result.current.status).toBe('procesando');

    // Record how many /chat/current calls happened so far (just the initial load)
    const callsBefore = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    // Simulate returning from background
    setVisibilityState('visible');
    await act(async () => { fireVisibilityChange(); await Promise.resolve(); });

    const callsAfter = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    expect(callsAfter).toBeGreaterThan(callsBefore);
  });

  it('does NOT call /chat/current when status is conectado (idle)', async () => {
    const fetchMock = makeFetchMock({
      'GET /chat/current': { messages: [] },
      'POST /events/visibility': {},
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    // After history load the status is 'conectado'
    expect(result.current.status).toBe('conectado');

    const callsBefore = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    setVisibilityState('visible');
    await act(async () => { fireVisibilityChange(); await Promise.resolve(); });

    const callsAfter = fetchMock.mock.calls.filter(
      ([url]) => url === '/chat/current',
    ).length;

    expect(callsAfter).toBe(callsBefore);
  });

  it('keeps procesando when DB has no assistant response yet', async () => {
    // First two calls: initial history load + visibility reconcile (turn still running)
    let callCount = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST' && url === '/chat/message') {
        return { ok: true, status: 202, json: async () => ({ turn_id: 'turn_vis_002', status: 'queued' }) };
      }
      if (method === 'POST') return { ok: true, status: 204, json: async () => ({}) };
      // GET /chat/current: first call returns empty; reconcile call returns [user msg only]
      callCount++;
      if (callCount === 1) return { ok: true, status: 200, json: async () => ({ messages: [] }) };
      return {
        ok: true, status: 200,
        json: async () => ({
          messages: [{ role: 'user', text: 'hola', created_at: '2026-01-01T00:00:00Z' }],
        }),
      };
    }));

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    await act(async () => { void result.current.sendMessage('hola'); });
    expect(result.current.status).toBe('procesando');

    setVisibilityState('visible');
    await act(async () => { fireVisibilityChange(); await Promise.resolve(); });

    // DB only has the user message (no response) → status must stay 'procesando'
    expect(result.current.status).toBe('procesando');
  });

  it('clears procesando when DB shows the assistant response arrived', async () => {
    let callCount = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST' && url === '/chat/message') {
        return { ok: true, status: 202, json: async () => ({ turn_id: 'turn_vis_003', status: 'queued' }) };
      }
      if (method === 'POST') return { ok: true, status: 204, json: async () => ({}) };
      callCount++;
      if (callCount === 1) return { ok: true, status: 200, json: async () => ({ messages: [] }) };
      // Reconcile call: response already in DB
      return {
        ok: true, status: 200,
        json: async () => ({
          messages: [
            { role: 'user',  text: 'hola',     created_at: '2026-01-01T00:00:00Z' },
            { role: 'sity',  text: 'Hola tú.', created_at: '2026-01-01T00:00:01Z' },
          ],
        }),
      };
    }));

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    await act(async () => { void result.current.sendMessage('hola'); });
    expect(result.current.status).toBe('procesando');

    setVisibilityState('visible');
    await act(async () => { fireVisibilityChange(); await Promise.resolve(); });

    // DB has both messages → response arrived while tab was hidden → clear procesando
    expect(result.current.status).toBe('conectado');
  });

  it('does not change status when fetch fails during procesando reconciliation', async () => {
    let callCount = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      const method = (init?.method ?? 'GET').toUpperCase();
      if (method === 'POST' && url === '/chat/message') {
        return { ok: true, status: 202, json: async () => ({ turn_id: 'turn_vis_004', status: 'queued' }) };
      }
      if (method === 'POST') return { ok: true, status: 204, json: async () => ({}) };
      callCount++;
      if (callCount === 1) return { ok: true, status: 200, json: async () => ({ messages: [] }) };
      // Reconcile fetch fails
      return { ok: false, status: 503, json: async () => ({}) };
    }));

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    await act(async () => { void result.current.sendMessage('hola'); });
    expect(result.current.status).toBe('procesando');

    setVisibilityState('visible');
    await act(async () => { fireVisibilityChange(); await Promise.resolve(); });

    // Conservative fallback: failed fetch must not set desconectado
    expect(result.current.status).toBe('procesando');
  });
});
