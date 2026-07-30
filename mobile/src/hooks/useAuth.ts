import { useState, useEffect } from 'react';

export type UserRole = 'guest' | 'user' | 'admin';

export interface CurrentUser {
  role: UserRole;
  id?: number;
  email?: string;
  displayName?: string;
}

interface AuthResult {
  ok: boolean;
  error?: string;
}

const API_BASE = '';

async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<{ data?: T; error?: string }> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (res.ok) {
      const data = (await res.json()) as T;
      return { data };
    }
    let error = `Error ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) error = body.detail;
    } catch { /* ignore */ }
    return { error };
  } catch {
    return { error: 'Sin conexión con el servidor' };
  }
}

interface MeResponse {
  role: UserRole;
  id?: number;
  email?: string;
  display_name?: string;
}

export function useAuth() {
  // null = loading; CurrentUser = resolved
  const [currentUser, setCurrentUser] = useState<CurrentUser | null>(null);

  useEffect(() => {
    void fetchMe();
  }, []);

  async function fetchMe() {
    const { data } = await apiFetch<MeResponse>('/auth/me');
    if (data) {
      setCurrentUser({
        role: data.role,
        id: data.id,
        email: data.email ?? undefined,
        displayName: data.display_name ?? undefined,
      });
    } else {
      // Fallback: treat as guest if /auth/me is unreachable
      setCurrentUser({ role: 'guest' });
    }
  }

  async function login(email: string, password: string): Promise<AuthResult> {
    const { data, error } = await apiFetch<{ ok: boolean; role: string }>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (data?.ok) {
      await fetchMe();
      return { ok: true };
    }
    return { ok: false, error: error ?? 'Error al iniciar sesión' };
  }

  async function register(email: string, password: string): Promise<AuthResult> {
    const { data, error } = await apiFetch<{ ok: boolean }>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    });
    if (data?.ok) {
      await fetchMe();
      return { ok: true };
    }
    return { ok: false, error: error ?? 'Error al registrarse' };
  }

  async function logout(): Promise<void> {
    await apiFetch('/auth/logout', { method: 'POST' });
    // Clear guest opt-in so the auth screen is shown again
    sessionStorage.removeItem('sity_guest_opted_in');
    await fetchMe();
  }

  async function forgotPassword(email: string): Promise<AuthResult> {
    const { data, error } = await apiFetch<{ ok: boolean }>('/auth/forgot-password', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
    if (data?.ok) return { ok: true };
    return { ok: false, error: error ?? 'Error al solicitar recuperación' };
  }

  async function resetPassword(token: string, newPassword: string): Promise<AuthResult> {
    const { data, error } = await apiFetch<{ ok: boolean }>('/auth/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword }),
    });
    if (data?.ok) return { ok: true };
    return { ok: false, error: error ?? 'Error al restablecer contraseña' };
  }

  function continueAsGuest() {
    sessionStorage.setItem('sity_guest_opted_in', 'true');
    // currentUser is already { role: 'guest' } — just mark the choice
    setCurrentUser((u) => u ?? { role: 'guest' });
  }

  return {
    currentUser,
    login,
    register,
    logout,
    forgotPassword,
    resetPassword,
    continueAsGuest,
    refreshUser: fetchMe,
  };
}

export type UseAuthResult = ReturnType<typeof useAuth>;
