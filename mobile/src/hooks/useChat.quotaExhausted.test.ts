/**
 * Regression for Hallazgo 18/H-07: UI must disable input after
 * model="user-message-guard" response is received.
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useChat } from './useChat';

// ── EventSource mock ──────────────────────────────────────────────────────────

type ESHandler = (e: { data: string }) => void;

class MockEventSource {
  static instances: MockEventSource[] = [];
  onmessage: ESHandler | null = null;
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

  emit(data: string) {
    this.onmessage?.({ data });
  }

  close() {}
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function stubFetch(responses: object[]) {
  let call = 0;
  vi.stubGlobal('fetch', vi.fn(async () => {
    const body = responses[Math.min(call++, responses.length - 1)];
    return { ok: true, status: 202, json: async () => body };
  }));
}

function sseEvent(payload: object): string {
  return JSON.stringify(payload);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

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

describe('useChat — quotaExhausted', () => {
  it('starts as false', async () => {
    stubFetch([{ messages: [] }]);
    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.quotaExhausted).toBe(false);
  });

  it('becomes true when response has model="user-message-guard"', async () => {
    // 1st fetch: history (GET /chat/current)
    // 2nd fetch: POST /chat/message → 202 with turn_id
    // 3rd fetch: POST /events/visibility
    stubFetch([
      { messages: [] },
      { turn_id: 'turn_test_001', status: 'queued' },
      {},
    ]);

    const { result } = renderHook(() => useChat('user:1'));

    // Wait for history load
    await act(async () => { await Promise.resolve(); });

    // Trigger sendMessage
    await act(async () => {
      void result.current.sendMessage('hola');
    });

    // Find the stream EventSource (url contains /chat/stream/)
    const streamEs = MockEventSource.instances.find((es) =>
      es.url.includes('/chat/stream/'),
    );
    expect(streamEs).toBeDefined();

    // Simulate SSE response with model="user-message-guard"
    await act(async () => {
      streamEs!.emit(sseEvent({
        type: 'response',
        data: {
          ok: true,
          text: 'Has alcanzado el límite diario de mensajes.',
          model: 'user-message-guard',
          artifacts: [],
        },
      }));
    });

    expect(result.current.quotaExhausted).toBe(true);
  });

  it('does NOT set quotaExhausted for normal assistant responses', async () => {
    stubFetch([
      { messages: [] },
      { turn_id: 'turn_test_002', status: 'queued' },
      {},
    ]);

    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => { await Promise.resolve(); });

    await act(async () => {
      void result.current.sendMessage('hola');
    });

    const streamEs = MockEventSource.instances.find((es) =>
      es.url.includes('/chat/stream/'),
    );

    await act(async () => {
      streamEs!.emit(sseEvent({
        type: 'response',
        data: { ok: true, text: 'Hola, ¿qué tal?', artifacts: [] },
      }));
    });

    expect(result.current.quotaExhausted).toBe(false);
  });

  it('resets to false when userKey changes (new session)', async () => {
    stubFetch([
      { messages: [] },
      { turn_id: 'turn_test_003', status: 'queued' },
      {},
      { messages: [] },
    ]);

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useChat(key),
      { initialProps: { key: 'user:1' } },
    );
    await act(async () => { await Promise.resolve(); });

    // Trigger guard response
    await act(async () => { void result.current.sendMessage('hola'); });

    const streamEs = MockEventSource.instances.find((es) =>
      es.url.includes('/chat/stream/'),
    );
    await act(async () => {
      streamEs!.emit(sseEvent({
        type: 'response',
        data: { ok: true, text: 'Límite.', model: 'user-message-guard', artifacts: [] },
      }));
    });

    expect(result.current.quotaExhausted).toBe(true);

    // Change session
    rerender({ key: 'user:2' });
    await act(async () => { await Promise.resolve(); });

    expect(result.current.quotaExhausted).toBe(false);
  });
});
