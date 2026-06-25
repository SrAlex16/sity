import { useState, useEffect } from 'react';
import { useDataset } from '../hooks/useDataset';
import type { DatasetCaptureRequest } from '../hooks/useDataset';
import { HelpModal } from '../components/HelpModal';
import styles from './DatasetScreen.module.css';

// ── Presets ──────────────────────────────────────────────────────────────────

type PresetKey = 'normal_use' | 'synthetic_claude_user' | 'human_guest' | 'demo_session' | 'debug_test';

const PRESETS: Record<PresetKey, Partial<CaptureForm>> = {
  normal_use:            { dataset_source: 'normal_use',            speaker_source: 'human_local',            dataset_eligible: true,  dataset_tags: '' },
  synthetic_claude_user: { dataset_source: 'synthetic_claude_user', speaker_source: 'synthetic_claude_user',  dataset_eligible: true,  dataset_tags: 'multi_persona' },
  human_guest:           { dataset_source: 'human_guest',           speaker_source: 'human_guest',            dataset_eligible: true,  dataset_tags: '' },
  demo_session:          { dataset_source: 'demo_session',          speaker_source: 'human_local',            dataset_eligible: true,  dataset_tags: 'demo' },
  debug_test:            { dataset_source: 'debug_test',            speaker_source: 'human_local',            dataset_eligible: false, dataset_tags: '' },
};

const DATASET_SOURCE_OPTIONS = ['normal_use', 'synthetic_claude_user', 'human_guest', 'demo_session', 'debug_test'] as const;
const SPEAKER_SOURCE_OPTIONS = ['human_local', 'synthetic_claude_user', 'human_guest'] as const;

// ── Form helpers ─────────────────────────────────────────────────────────────

interface CaptureForm {
  enabled: boolean;
  dataset_source: string;
  speaker_label: string;
  speaker_source: string;
  speaker_confidence: string;
  dataset_eligible: boolean;
  dataset_tags: string;
}

import type { DatasetCaptureContext } from '../hooks/useDataset';

function captureToForm(ctx: DatasetCaptureContext | null): CaptureForm {
  return {
    enabled:            ctx?.enabled              ?? false,
    dataset_source:     ctx?.dataset_source       ?? 'normal_use',
    speaker_label:      ctx?.speaker_label        ?? '',
    speaker_source:     ctx?.speaker_source       ?? '',
    speaker_confidence: ctx?.speaker_confidence != null ? String(ctx.speaker_confidence) : '',
    dataset_eligible:   ctx?.dataset_eligible     ?? true,
    dataset_tags:       ctx?.dataset_tags?.join(', ') ?? '',
  };
}

function formToRequest(form: CaptureForm): DatasetCaptureRequest {
  const conf = form.speaker_confidence.trim() ? parseFloat(form.speaker_confidence) : null;
  return {
    enabled:            form.enabled,
    dataset_source:     form.dataset_source || 'normal_use',
    speaker_label:      form.speaker_label.trim() || null,
    speaker_source:     form.speaker_source.trim() || null,
    speaker_confidence: conf,
    dataset_eligible:   form.dataset_eligible,
    dataset_tags:       form.dataset_tags.split(',').map((t) => t.trim()).filter(Boolean),
  };
}

// ── Screen ───────────────────────────────────────────────────────────────────

export function DatasetScreen() {
  const { capture, isLoading, error, save, disable, reload } = useDataset();
  const [form, setForm] = useState<CaptureForm>(() => captureToForm(null));
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [bgValue] = useState<string>(() => localStorage.getItem('sity_bg') ?? '');

  useEffect(() => {
    if (capture) setForm(captureToForm(capture));
  }, [capture]);

  const backgroundStyle: React.CSSProperties = bgValue
    ? bgValue.startsWith('data:')
      ? { backgroundImage: `url(${bgValue})`, backgroundSize: 'cover', backgroundPosition: 'center' }
      : { background: bgValue }
    : {};

  const busy = saving || isLoading;
  const isActive = capture?.enabled ?? false;

  const patch = (delta: Partial<CaptureForm>) => setForm((p) => ({ ...p, ...delta }));

  const applyPreset = (key: PresetKey) => {
    setForm((p) => ({ ...p, ...PRESETS[key] }));
  };

  const validate = (): boolean => {
    setFormError(null);
    if (form.enabled && !form.speaker_source.trim()) {
      setFormError('speaker_source es obligatorio cuando capture está activo.');
      return false;
    }
    const conf = form.speaker_confidence.trim();
    if (conf) {
      const n = parseFloat(conf);
      if (isNaN(n) || n < 0 || n > 1) {
        setFormError('speaker_confidence debe estar entre 0 y 1.');
        return false;
      }
    }
    return true;
  };

  const handleSave = async () => {
    if (!validate()) return;
    setSaving(true);
    try { await save(formToRequest(form)); } catch { /* shown via hook */ } finally { setSaving(false); }
  };

  const handleDisable = async () => {
    setSaving(true);
    try { await disable(); } catch { /* shown via hook */ } finally { setSaving(false); }
  };

  const handleRestorePersonality = async () => {
    setSaving(true);
    try {
      const r = await fetch('/settings/personality/reset', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
    } catch { /* silent */ } finally { setSaving(false); }
  };

  const activeLabel = isActive
    ? `Activo: ${capture?.dataset_source ?? ''}${capture?.speaker_label ? ` / ${capture.speaker_label}` : ''}`
    : 'Desactivado';

  return (
    <div className={styles.screen}>
      {bgValue && <div className={styles.background} style={backgroundStyle} />}
      <div className={styles.overlay} />

      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleMain}>Dataset Capture</span>
          <span className={`${styles.titleSub} ${isActive ? styles.titleSubActive : ''}`}>
            {activeLabel}
          </span>
        </div>
        <button className={styles.helpBtn} onClick={() => setHelpOpen(true)}>?</button>
      </header>

      {/* Content */}
      <div className={styles.content}>
        {(error || formError) && (
          <p className={styles.errorMsg}>{formError ?? error}</p>
        )}

        {!capture && isLoading && <p className={styles.loading}>Cargando…</p>}

        {/* Capture toggle */}
        <div className={styles.section}>
          <label className={styles.checkboxRow}>
            <input
              type="checkbox"
              className={styles.hiddenInput}
              checked={form.enabled}
              onChange={(e) => patch({ enabled: e.target.checked })}
            />
            <span className={`${styles.checkboxIndicator} ${styles.checkboxLarge}`} />
            <div>
              <p className={styles.fieldLabel}>Capture activo</p>
              <p className={styles.fieldHint}>Registra las conversaciones para el dataset LoRA</p>
            </div>
          </label>
        </div>

        {/* Presets */}
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Preset</p>
          <div className={styles.chipRow}>
            {(Object.keys(PRESETS) as PresetKey[]).map((key) => (
              <button
                key={key}
                className={`${styles.chip} ${form.dataset_source === key ? styles.chipActive : ''}`}
                onClick={() => applyPreset(key)}
                disabled={busy}
              >
                {key}
              </button>
            ))}
          </div>
        </div>

        {/* Fields grid */}
        <div className={styles.fieldsGrid}>
          <div className={styles.field}>
            <label className={styles.fieldLabel}>dataset_source</label>
            <select
              className={styles.select}
              value={form.dataset_source}
              onChange={(e) => patch({ dataset_source: e.target.value })}
            >
              {DATASET_SOURCE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel}>speaker_source</label>
            <select
              className={styles.select}
              value={form.speaker_source}
              onChange={(e) => patch({ speaker_source: e.target.value })}
            >
              <option value="">— ninguno —</option>
              {SPEAKER_SOURCE_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel}>speaker_label</label>
            <input
              type="text"
              className={styles.input}
              value={form.speaker_label}
              onChange={(e) => patch({ speaker_label: e.target.value })}
              placeholder="alex, guest_01…"
            />
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel}>speaker_confidence (0–1)</label>
            <input
              type="number"
              className={styles.input}
              min="0" max="1" step="0.05"
              value={form.speaker_confidence}
              onChange={(e) => patch({ speaker_confidence: e.target.value })}
              placeholder="0.9"
            />
          </div>

          <div className={`${styles.field} ${styles.fieldFull}`}>
            <label className={styles.fieldLabel}>dataset_tags <span className={styles.fieldHint}>(coma-separados)</span></label>
            <input
              type="text"
              className={styles.input}
              value={form.dataset_tags}
              onChange={(e) => patch({ dataset_tags: e.target.value })}
              placeholder="multi_persona, casual"
            />
          </div>

          <div className={`${styles.field} ${styles.fieldFull}`}>
            <label className={styles.checkboxRow}>
              <input
                type="checkbox"
                className={styles.hiddenInput}
                checked={form.dataset_eligible}
                onChange={(e) => patch({ dataset_eligible: e.target.checked })}
              />
              <span className={styles.checkboxIndicator} />
              <div>
                <span className={styles.fieldLabel}>dataset_eligible</span>
                <p className={styles.fieldHint}>Incluir en el pool de candidatos para fine-tuning</p>
              </div>
            </label>
          </div>
        </div>
      </div>

      {/* Footer */}
      <div className={styles.footer}>
        <div className={styles.footerRow}>
          <button className={`${styles.btn} ${styles.btnCyan}`} onClick={handleSave} disabled={busy}>
            {saving ? '…' : 'Guardar'}
          </button>
          <button className={`${styles.btn} ${styles.btnMagenta}`} onClick={handleDisable} disabled={busy || !isActive}>
            Desactivar
          </button>
        </div>
        <button
          className={`${styles.btn} ${styles.btnSecondary}`}
          onClick={() => void reload()}
          disabled={busy}
        >
          Recargar
        </button>
        <button
          className={`${styles.btn} ${styles.btnSecondary}`}
          onClick={handleRestorePersonality}
          disabled={busy}
        >
          Restaurar valores de personalidad
        </button>
      </div>

      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} title="Dataset Capture">
        <p><strong>dataset_source</strong> — Tipo de sesión. Define cómo se agrupa este dato en la exportación.</p>
        <p><strong>speaker_source</strong> — Indica si el input viene de una persona o de Claude.</p>
        <p><strong>speaker_label</strong> — Etiqueta libre para identificar quién habla.</p>
        <p><strong>speaker_confidence</strong> — Confianza en la atribución del hablante (0 = ninguna, 1 = certeza).</p>
        <p><strong>dataset_tags</strong> — Etiquetas para los buckets de entrenamiento.</p>
        <p><strong>dataset_eligible</strong> — Si este par entra en el pool de candidatos para fine-tuning.</p>
        <p>Los presets rellenan varios campos a la vez para los flujos más comunes.</p>
      </HelpModal>
    </div>
  );
}
