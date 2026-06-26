import { useState, useEffect } from 'react';
import { useVoice, VOICE_DEFAULTS } from '../hooks/useVoice';
import type { VoiceSettings } from '../hooks/useVoice';
import styles from './VoiceScreen.module.css';

// ── Icons ────────────────────────────────────────────────────────────────────

function IconReload() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
      strokeLinecap="round" strokeLinejoin="round" width="16" height="16">
      <path d="M23 4v6h-6" />
      <path d="M1 20v-6h6" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  );
}

// ── Labels ───────────────────────────────────────────────────────────────────

const MODE_LABELS: Record<VoiceSettings['voice_response_mode'], string> = {
  always: 'Siempre',
  never: 'Nunca',
  symmetric: 'Simétrico (solo si el mensaje fue de voz)',
};

const LONG_LABELS: Record<VoiceSettings['voice_long_response_action'], string> = {
  split: 'Dividir en notas de voz',
  text_only: 'Solo texto (sin audio)',
};

// ── Screen ───────────────────────────────────────────────────────────────────

export function VoiceScreen() {
  const { settings, isLoading, error, save, reload } = useVoice();
  const [form, setForm] = useState<VoiceSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [bgValue] = useState<string>(() => localStorage.getItem('sity_bg') ?? '');

  useEffect(() => {
    if (settings) setForm(settings);
  }, [settings]);

  const backgroundStyle: React.CSSProperties = bgValue
    ? bgValue.startsWith('data:')
      ? { backgroundImage: `url(${bgValue})`, backgroundSize: 'cover', backgroundPosition: 'center' }
      : { background: bgValue }
    : {};

  const busy = saving || isLoading;

  const handleSave = async () => {
    if (!form) return;
    setSaving(true);
    try { await save(form); } catch { /* error shown via hook */ } finally { setSaving(false); }
  };

  const handleRestore = async () => {
    setForm(VOICE_DEFAULTS);
    setSaving(true);
    try { await save(VOICE_DEFAULTS); } catch { /* error shown via hook */ } finally { setSaving(false); }
  };

  const patch = (delta: Partial<VoiceSettings>) =>
    setForm((prev) => prev ? { ...prev, ...delta } : prev);

  return (
    <div className={styles.screen}>
      {bgValue && <div className={styles.background} style={backgroundStyle} />}
      <div className={styles.overlay} />

      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleJp}>音声</span>
          <span className={styles.titleEs}>Voz</span>
        </div>
        <button className={styles.reloadBtn} onClick={() => void reload()} disabled={busy}>
          <IconReload />
          <span>Recargar</span>
        </button>
      </header>

      {/* Content */}
      <div className={styles.content}>
        {error && <p className={styles.errorMsg}>{error}</p>}

        {!form && isLoading && <p className={styles.loading}>Cargando…</p>}

        {form && (
          <>
            {/* Modo de respuesta */}
            <div className={styles.section}>
              <p className={styles.sectionJp}>レスポンスモード</p>
              <p className={styles.sectionEs}>Modo de respuesta de voz</p>
              <div className={styles.radioGroup}>
                {(['always', 'never', 'symmetric'] as const).map((mode) => (
                  <label key={mode} className={styles.radioRow}>
                    <input
                      type="radio"
                      className={styles.hiddenInput}
                      name="voice_response_mode"
                      value={mode}
                      checked={form.voice_response_mode === mode}
                      onChange={() => patch({ voice_response_mode: mode })}
                    />
                    <span className={styles.radioIndicator} />
                    <span className={styles.optionText}>{MODE_LABELS[mode]}</span>
                  </label>
                ))}
              </div>
            </div>

            {/* Transcripción junto al audio */}
            <div className={styles.section}>
              <label className={styles.checkboxRow}>
                <input
                  type="checkbox"
                  className={styles.hiddenInput}
                  checked={form.voice_include_text}
                  onChange={(e) => patch({ voice_include_text: e.target.checked })}
                />
                <span className={styles.checkboxIndicator} />
                <div>
                  <p className={styles.sectionJp}>テキスト起こしも含む</p>
                  <p className={styles.sectionEs}>Incluir transcripción de texto junto al audio</p>
                </div>
              </label>
            </div>

            {/* Respuestas largas */}
            <div className={styles.section}>
              <p className={styles.sectionJp}>長いレスポンス</p>
              <p className={styles.sectionEs}>Respuestas largas</p>
              <div className={styles.radioGroup}>
                {(['split', 'text_only'] as const).map((action) => (
                  <label key={action} className={styles.radioRow}>
                    <input
                      type="radio"
                      className={styles.hiddenInput}
                      name="voice_long_response_action"
                      value={action}
                      checked={form.voice_long_response_action === action}
                      onChange={() => patch({ voice_long_response_action: action })}
                    />
                    <span className={styles.radioIndicator} />
                    <span className={styles.optionText}>{LONG_LABELS[action]}</span>
                  </label>
                ))}
              </div>
            </div>
          </>
        )}
      </div>

      {/* Footer actions */}
      <div className={styles.footer}>
        <button className={`${styles.btn} ${styles.btnCyan}`} onClick={handleSave} disabled={busy || !form}>
          {saving ? '…' : 'Guardar'}
        </button>
        <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={handleRestore} disabled={busy}>
          Restaurar valores de voz
        </button>
      </div>
    </div>
  );
}
