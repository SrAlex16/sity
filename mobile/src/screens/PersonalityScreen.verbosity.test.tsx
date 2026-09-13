/**
 * Regression test: PersonalityScreen debe NO llamar a /settings/verbosity
 * para roles sin permiso (guest, user normal). Solo admin tiene acceso.
 *
 * Contexto: verbosity cambió a admin-only en 2026-09-13. El bug consistía en
 * que la sección se ocultaba visualmente para no-admin pero el fetch
 * seguía disparándose al montar el componente.
 */
import { render, act } from '@testing-library/react';
import { describe, it, expect, vi, afterEach } from 'vitest';

// ── Mocks de subcomponentes para aislar PersonalityScreen ────────────────────

vi.mock('../components/MoodFace', () => ({ MoodFace: () => null }));
vi.mock('../components/NeonSlider', () => ({ NeonSlider: () => null }));
vi.mock('../components/HelpModal', () => ({ HelpModal: () => null }));
vi.mock('../components/AltersPanel', () => ({ AltersPanel: () => null }));
vi.mock('../components/InfoTooltip', () => ({ InfoTooltip: () => null }));
vi.mock('../components/PersonalitySliderItem', () => ({
  PersonalitySliderItem: () => null,
  PARAM_META: {},
}));
vi.mock('framer-motion', () => ({
  motion: {
    span: ({ children, style, className }: React.HTMLAttributes<HTMLSpanElement>) =>
      <span style={style} className={className}>{children}</span>,
  },
}));
vi.mock('../hooks/usePersonality', () => ({
  usePersonality: () => ({
    settings: null,
    isLoading: false,
    adjust: vi.fn(),
    reset: vi.fn(),
    reload: vi.fn(),
  }),
}));

import { PersonalityScreen } from './PersonalityScreen';

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeFetchSpy() {
  const spy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
  vi.stubGlobal('fetch', spy);
  return spy;
}

function verbosityCalls(spy: ReturnType<typeof vi.fn>): string[] {
  return (spy.mock.calls as [string][])
    .map(([url]) => url)
    .filter((url) => url?.includes('/settings/verbosity'));
}

// ── Tests ─────────────────────────────────────────────────────────────────────

afterEach(() => { vi.restoreAllMocks(); });

describe('PersonalityScreen — verbosity fetch guard', () => {

  it('NO llama a /settings/verbosity cuando role=guest', async () => {
    const spy = makeFetchSpy();
    render(<PersonalityScreen role="guest" />);
    // Flush microtasks/effects
    await act(async () => { await Promise.resolve(); });
    expect(verbosityCalls(spy)).toHaveLength(0);
  });

  it('NO llama a /settings/verbosity cuando role=user (no-admin)', async () => {
    const spy = makeFetchSpy();
    render(<PersonalityScreen role="user" />);
    await act(async () => { await Promise.resolve(); });
    expect(verbosityCalls(spy)).toHaveLength(0);
  });

  it('SÍ llama a /settings/verbosity cuando role=admin', async () => {
    const spy = makeFetchSpy();
    render(<PersonalityScreen role="admin" />);
    await act(async () => { await Promise.resolve(); });
    expect(verbosityCalls(spy).length).toBeGreaterThan(0);
  });

});
