/**
 * Tests for draft persistence in BugReportModal.
 *
 * The modal saves {observations, severity} to localStorage key
 * "sity_bug_report_draft" on every change. On re-open the draft
 * is restored. On successful submit the draft is cleared.
 *
 * These tests verify the draft helpers in isolation (pure functions).
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';

const _LS_KEY = 'sity_bug_report_draft';

// Inline copies of the helpers from BugReportModal.tsx so we can test them
// without importing the full React component.

function loadDraft(): { observations: string; severity: string } {
  try {
    const raw = localStorage.getItem(_LS_KEY);
    if (raw) return JSON.parse(raw) as { observations: string; severity: string };
  } catch { /* ignore */ }
  return { observations: '', severity: 'media' };
}

function saveDraft(state: { observations: string; severity: string }) {
  try {
    localStorage.setItem(_LS_KEY, JSON.stringify(state));
  } catch { /* ignore */ }
}

function clearDraft() {
  try { localStorage.removeItem(_LS_KEY); } catch { /* ignore */ }
}

// ── setup ─────────────────────────────────────────────────────────────────────

beforeEach(() => { localStorage.clear(); });
afterEach(() => { localStorage.clear(); });

// ── tests ─────────────────────────────────────────────────────────────────────

describe('BugReportModal — draft persistence', () => {

  it('loadDraft returns empty defaults when no draft is stored', () => {
    const draft = loadDraft();
    expect(draft.observations).toBe('');
    expect(draft.severity).toBe('media');
  });

  it('saveDraft persists observations and severity', () => {
    saveDraft({ observations: 'El botón no funciona.', severity: 'alta' });
    const raw = localStorage.getItem(_LS_KEY);
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.observations).toBe('El botón no funciona.');
    expect(parsed.severity).toBe('alta');
  });

  it('loadDraft restores a saved draft', () => {
    saveDraft({ observations: 'Texto guardado.', severity: 'crítica' });
    const draft = loadDraft();
    expect(draft.observations).toBe('Texto guardado.');
    expect(draft.severity).toBe('crítica');
  });

  it('close with data written → re-open → data still there', () => {
    // Simulate: user types, closes modal (draft saved), re-opens
    saveDraft({ observations: 'Datos escritos antes de cerrar.', severity: 'baja' });
    // Re-open: loadDraft() is called on mount
    const draft = loadDraft();
    expect(draft.observations).toBe('Datos escritos antes de cerrar.');
    expect(draft.severity).toBe('baja');
    expect(localStorage.getItem(_LS_KEY)).not.toBeNull();
  });

  it('clearDraft removes the localStorage entry', () => {
    saveDraft({ observations: 'Texto.', severity: 'media' });
    expect(localStorage.getItem(_LS_KEY)).not.toBeNull();
    clearDraft();
    expect(localStorage.getItem(_LS_KEY)).toBeNull();
  });

  it('after successful submit draft is cleared → re-open shows empty form', () => {
    saveDraft({ observations: 'Bug importante.', severity: 'alta' });
    // Simulate successful submit
    clearDraft();
    // Re-open
    const draft = loadDraft();
    expect(draft.observations).toBe('');
    expect(draft.severity).toBe('media');
  });

  it('loadDraft handles corrupt JSON gracefully', () => {
    localStorage.setItem(_LS_KEY, 'not-valid-json{{{{');
    const draft = loadDraft();
    expect(draft.observations).toBe('');
    expect(draft.severity).toBe('media');
  });
});
