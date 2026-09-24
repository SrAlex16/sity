/**
 * Tests for the ID-based clearMessages() mechanism.
 *
 * clearMessages() stores the last known DB integer id in localStorage.
 * loadHistory() filters out messages with id <= the stored value.
 * Old ISO-timestamp keys are deleted and all messages are shown (migration).
 */
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useChat } from './useChat';

// ── EventSource stub ──────────────────────────────────────────────────────────

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

function makeMessages(ids: number[]) {
  return ids.map((id) => ({
    id,
    role: id % 2 === 1 ? 'user' : 'sity',
    text: `msg ${id}`,
    created_at: `2026-09-24T10:00:0${id}.000Z`,
  }));
}

function stubHistory(msgs: object[]) {
  vi.stubGlobal('fetch', vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => ({ messages: msgs }),
  })));
}

beforeEach(() => {
  MockEventSource.instances = [];
  vi.stubGlobal('EventSource', MockEventSource);
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('clearMessages — ID-based filter', () => {
  it('shows all messages when no clear key is set', async () => {
    stubHistory(makeMessages([1, 2, 3]));
    const { result } = renderHook(() => useChat('user:1'));

    await act(async () => {});

    expect(result.current.messages).toHaveLength(3);
  });

  it('clearMessages() stores last id; remount shows only messages after that id', async () => {
    // Simulates the real-world flow: user clears chat, closes app, reopens.
    stubHistory(makeMessages([1, 2, 3]));
    const { result, unmount } = renderHook(() => useChat('user:1'));
    await act(async () => {});

    // Clear after seeing messages 1-3 (last known id = 3)
    act(() => { result.current.clearMessages(); });
    expect(result.current.messages).toHaveLength(0);
    unmount(); // simulate closing the app

    // Reopen: messages 4 and 5 were added while the app was closed
    stubHistory(makeMessages([1, 2, 3, 4, 5]));
    const { result: result2 } = renderHook(() => useChat('user:1'));
    await act(async () => {});

    // Messages 1-3 are hidden (id <= 3), 4 and 5 are visible (id > 3)
    expect(result2.current.messages).toHaveLength(2);
    expect(result2.current.messages.map((m) => (m as any).text ?? '')).toEqual(
      expect.arrayContaining(['msg 4', 'msg 5']),
    );
  });

  it('messages with id > cleared marker are visible regardless of created_at (no clock skew)', async () => {
    // Old timestamp-based approach would break if server clock were ahead of client.
    // With ID-based filtering there is no clock comparison at all.
    const msgs = [
      { id: 10, role: 'user', text: 'before clear', created_at: '2026-09-24T09:00:00.000Z' },
      { id: 11, role: 'sity', text: 'after clear',  created_at: '2026-09-24T09:00:01.000Z' },
    ];
    stubHistory(msgs.slice(0, 1)); // only msg 10 on first load
    const { result, unmount } = renderHook(() => useChat('user:1'));
    await act(async () => {});

    act(() => { result.current.clearMessages(); });
    unmount();

    // Remount with both messages — id 11 should be visible
    stubHistory(msgs);
    const { result: result2 } = renderHook(() => useChat('user:1'));
    await act(async () => {});
    expect(result2.current.messages).toHaveLength(1);
    expect((result2.current.messages[0] as any).text).toBe('after clear');
  });

  it('migration: old ISO-format key is deleted and all messages become visible', async () => {
    const lsKey = 'sity_chat_cleared_user:1';
    // Set an old-format ISO timestamp that would hide everything
    localStorage.setItem(lsKey, '2026-09-24T23:59:59.000Z');

    stubHistory(makeMessages([1, 2, 3]));
    const { result } = renderHook(() => useChat('user:1'));
    await act(async () => {});

    // Old key should have been deleted
    expect(localStorage.getItem(lsKey)).toBeNull();
    // All 3 messages should be visible
    expect(result.current.messages).toHaveLength(3);
  });

  it('Guest clear does not affect Admin view (keys are scoped to userKey)', async () => {
    stubHistory(makeMessages([1, 2]));
    const { result: guestResult } = renderHook(() => useChat('guest'));
    await act(async () => {});
    act(() => { guestResult.current.clearMessages(); });

    // Admin session should not have any clear key set
    expect(localStorage.getItem('sity_chat_cleared_user:1')).toBeNull();
  });
});
