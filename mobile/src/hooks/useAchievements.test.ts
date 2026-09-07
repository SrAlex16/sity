import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useAchievements } from './useAchievements';

// Minimal achievement factory
const makeAchievement = (slug: string, unlocked: boolean) => ({
  slug,
  category: 'test',
  name: slug,
  description: '',
  unlocked,
  unlocked_at: unlocked ? '2026-01-01T00:00:00Z' : null,
});

const GUEST_RESPONSE = {
  achievements: [
    makeAchievement('hello_world', false),
    makeAchievement('remember_me', false),
  ],
  unlocked_count: 0,
  total_count: 2,
};

const AUTH_RESPONSE = {
  achievements: [
    makeAchievement('hello_world', true),
    makeAchievement('remember_me', true),
  ],
  unlocked_count: 2,
  total_count: 2,
};

function mockFetch(responses: object[]) {
  let call = 0;
  vi.stubGlobal('fetch', vi.fn(async () => {
    const body = responses[Math.min(call++, responses.length - 1)];
    return { ok: true, json: async () => body };
  }));
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe('useAchievements — escenario JWT expirado', () => {
  it('NO dispara notificaciones cuando userId cambia de undefined a autenticado con logros ya desbloqueados', async () => {
    // Primera llamada: guest → todo bloqueado
    // Siguientes llamadas: usuario autenticado → logros desbloqueados
    mockFetch([GUEST_RESPONSE, AUTH_RESPONSE, AUTH_RESPONSE]);

    const { result, rerender } = renderHook(
      ({ userId }: { userId?: number }) => useAchievements(userId),
      { initialProps: { userId: undefined as number | undefined } },
    );

    // Esperar al fetch inicial (guest)
    await act(async () => { await Promise.resolve(); });

    expect(result.current.notification).toBeNull();

    // Login: userId pasa de undefined a 1
    rerender({ userId: 1 });

    // Esperar al nuevo fetch inicial (autenticado, initial=true → sin comparación)
    await act(async () => { await Promise.resolve(); });

    // Dejar que el useEffect de la cola de notificaciones corra
    await act(async () => { await Promise.resolve(); });

    // ASERCIÓN CLAVE: ninguna notificación debe haberse disparado
    // porque prevUnlocked se resetea a null antes del fetch inicial post-login.
    expect(result.current.notification).toBeNull();
  });

  it('SÍ dispara notificaciones en un poll POST-login si se desbloquea un logro nuevo', async () => {
    // Primera llamada: inicial post-login con hello_world ya desbloqueado (baseline)
    // Segunda llamada: poll — remember_me recién desbloqueado
    const baselineResponse = {
      achievements: [
        makeAchievement('hello_world', true),
        makeAchievement('remember_me', false),
      ],
      unlocked_count: 1,
      total_count: 2,
    };
    const pollResponse = {
      achievements: [
        makeAchievement('hello_world', true),
        makeAchievement('remember_me', true),
      ],
      unlocked_count: 2,
      total_count: 2,
    };
    mockFetch([baselineResponse, pollResponse]);

    const { result } = renderHook(() => useAchievements(1));

    // Esperar fetch inicial → establece baseline {hello_world}
    await act(async () => { await Promise.resolve(); });
    expect(result.current.notification).toBeNull();

    // Avanzar el timer de polling 30s → fetchData(false) con remember_me desbloqueado
    await act(async () => { vi.advanceTimersByTime(30_000); });
    await act(async () => { await Promise.resolve(); });

    // La notificación debe haberse disparado para remember_me
    expect(result.current.notification).not.toBeNull();
    expect(result.current.notification?.slug).toBe('remember_me');
  });
});
