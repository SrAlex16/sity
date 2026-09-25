import { useState, useEffect } from 'react';
import { useDataset } from '../hooks/useDataset';
import { useDebug } from '../hooks/useDebug';
import type { DatasetCaptureRequest } from '../hooks/useDataset';
import type { TraceEvent, DatasetStats } from '../hooks/useDebug';
import { HelpModal } from '../components/HelpModal';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './DevToolsScreen.module.css';

// ── Internal tab types ────────────────────────────────────────────────────────

type DevTab = 'dataset' | 'debug';

// ── Dataset capture ───────────────────────────────────────────────────────────

type PresetKey = 'normal_use' | 'synthetic_claude_user' | 'human_guest' | 'demo_session' | 'debug_test';

const PRESETS: Record<PresetKey, Partial<CaptureForm>> = {
  normal_use:            { dataset_source: 'normal_use',            speaker_source: 'human_local',           dataset_eligible: true,  dataset_tags: '' },
  synthetic_claude_user: { dataset_source: 'synthetic_claude_user', speaker_source: 'synthetic_claude_user', dataset_eligible: true,  dataset_tags: 'multi_persona' },
  human_guest:           { dataset_source: 'human_guest',           speaker_source: 'human_guest',           dataset_eligible: true,  dataset_tags: '' },
  demo_session:          { dataset_source: 'demo_session',          speaker_source: 'human_local',           dataset_eligible: true,  dataset_tags: 'demo' },
  debug_test:            { dataset_source: 'debug_test',            speaker_source: 'human_local',           dataset_eligible: false, dataset_tags: '' },
};

const DATASET_SOURCE_OPTIONS = ['normal_use', 'synthetic_claude_user', 'human_guest', 'demo_session', 'debug_test'] as const;
const SPEAKER_SOURCE_OPTIONS = ['human_local', 'synthetic_claude_user', 'human_guest'] as const;

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

// ── Dataset stats sub-components ──────────────────────────────────────────────

function DatasetStatsSection({ stats, loading }: { stats: DatasetStats | null; loading: boolean }) {
  if (loading && !stats) return <p className={styles.loading}>Cargando estadísticas…</p>;
  if (!stats) return null;

  const sortedTargets = Object.entries(stats.targets).sort(
    ([, a], [, b]) => (b.target - b.count) - (a.target - a.count),
  );
  const tagEntries = Object.entries(stats.by_tag).sort(([, a], [, b]) => b - a);
  const sourceEntries = Object.entries(stats.by_source).sort(([, a], [, b]) => b - a);

  return (
    <>
      <div className={styles.statsHeader}>
        <p className={styles.statsTitle}>Dataset LoRA v1</p>
        <span className={styles.statsComputedAt}>
          {new Date(stats.computed_at).toLocaleString()}
          {loading && ' · actualizando…'}
        </span>
      </div>

      <div className={styles.statsCards}>
        {[
          { label: 'Totales', value: stats.total_pairs },
          { label: 'Utilizables', value: stats.usable_pairs },
          { label: 'Sin tone_meta', value: stats.missing_tone_meta },
          { label: 'Operacionales', value: stats.operational_pairs },
          { label: 'Inelegibles', value: stats.ineligible_pairs },
        ].map(({ label, value }) => (
          <div key={label} className={styles.statCard}>
            <div className={styles.statValue}>{value}</div>
            <div className={styles.statLabel}>{label}</div>
          </div>
        ))}
      </div>

      {sortedTargets.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Targets por bucket</p>
          {sortedTargets.map(([bucket, data]) => (
            <div key={bucket} className={styles.bucketRow}>
              <div className={styles.bucketHeader}>
                <span className={styles.bucketName}>{bucket}</span>
                <span className={styles.bucketCount}>{data.count}/{data.target} ({Math.round(data.progress * 100)}%)</span>
              </div>
              <div className={styles.progressBar}>
                <div className={styles.progressFill} style={{ width: `${data.progress * 100}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {sourceEntries.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Por fuente</p>
          <div>
            {sourceEntries.map(([src, count]) => (
              <span key={src} className={styles.tagChip}>{src}: <span className={styles.tagCount}>{count}</span></span>
            ))}
          </div>
        </div>
      )}

      {tagEntries.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Tags</p>
          <div>
            {tagEntries.map(([tag, count]) => (
              <span key={tag} className={styles.tagChip}>{tag}: <span className={styles.tagCount}>{count}</span></span>
            ))}
          </div>
        </div>
      )}

      {stats.recent_pairs.length > 0 && (
        <div>
          <p className={styles.statsTitle} style={{ padding: '12px 16px 8px' }}>Últimos pares</p>
          {stats.recent_pairs.map((pair, i) => (
            <div key={i} className={styles.recentPairCard}>
              <div className={styles.recentPairMeta}>
                <span className={styles.recentPairTime}>{new Date(pair.created_at).toLocaleString()}</span>
                <span className={styles.recentPairBucket}>{pair.primary_bucket}</span>
                <span className={styles.recentPairTime}>{pair.dataset_source}</span>
              </div>
              <p className={styles.recentPairText}>U: {pair.user_text}</p>
              <p className={`${styles.recentPairText} ${styles.recentPairSity}`}>S: {pair.sity_text}</p>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ── Debug trace sub-component ─────────────────────────────────────────────────

function EventCard({ event }: { event: TraceEvent }) {
  return (
    <div className={styles.eventCard}>
      <div className={styles.eventHeader}>
        <div>
          <div className={styles.eventName}>{event.event}</div>
          <div className={styles.eventMeta}>{event.module} · {new Date(event.timestamp).toLocaleTimeString()}</div>
        </div>
        <span className={styles.eventLevel}>{event.level}</span>
      </div>
      <pre className={styles.eventPre}>{JSON.stringify(event.payload, null, 2)}</pre>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function DevToolsScreen({ uiLang = 'es' }: { uiLang?: UiLang }) {
  const tl = TRANSLATIONS[uiLang].dataset;
  const { capture, isLoading: captureLoading, error: captureError, save, disable, reload: reloadCapture } = useDataset();
  const { recentEvents, lastTraceId, lastTraceEvents, datasetStats, isLoading: debugLoading, error: debugError, reload: reloadDebug } = useDebug();

  const [tab, setTab] = useState<DevTab>('dataset');
  const [form, setForm] = useState<CaptureForm>(() => captureToForm(null));
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);

  useEffect(() => {
    if (capture) setForm(captureToForm(capture));
  }, [capture]);

  useEffect(() => {
    void reloadDebug();
  }, [tab, reloadDebug]);

  const busy = saving || captureLoading;
  const isActive = capture?.enabled ?? false;

  const patch = (delta: Partial<CaptureForm>) => setForm((p) => ({ ...p, ...delta }));

  const applyPreset = (key: PresetKey) => setForm((p) => ({ ...p, ...PRESETS[key] }));

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
    ? `${tl.activePrefix}: ${capture?.dataset_source ?? ''}${capture?.speaker_label ? ` / ${capture.speaker_label}` : ''}`
    : tl.inactive;

  return (
    <div className={styles.screen}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleMain}>Dev Tools</span>
          <span className={`${styles.titleSub} ${tab === 'dataset' && isActive ? styles.titleSubActive : ''}`}>
            {tab === 'dataset' ? activeLabel : (lastTraceId ?? 'sin traza')}
          </span>
        </div>
        <button className={styles.helpBtn} onClick={() => setHelpOpen(true)}>?</button>
      </header>

      {/* Internal tabs */}
      <div className={styles.tabsRow}>
        <button
          className={`${styles.tabBtn} ${tab === 'dataset' ? styles.tabBtnActive : ''}`}
          onClick={() => setTab('dataset')}
        >
          Dataset
        </button>
        <button
          className={`${styles.tabBtn} ${tab === 'debug' ? styles.tabBtnActive : ''}`}
          onClick={() => setTab('debug')}
        >
          Debug
        </button>
      </div>

      {/* Tab content */}
      <div className={styles.tabContent}>

        {/* ── Dataset tab ── */}
        {tab === 'dataset' && (
          <>
            {(captureError || formError) && (
              <p className={styles.errorMsg}>{formError ?? captureError}</p>
            )}

            {!capture && captureLoading && <p className={styles.loading}>{tl.loading}</p>}

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
                  <p className={styles.fieldLabel}>{tl.captureActive}</p>
                  <p className={styles.fieldHint}>{tl.captureHint}</p>
                </div>
              </label>
            </div>

            {/* Presets */}
            <div className={styles.section}>
              <p className={styles.sectionLabel}>{tl.preset}</p>
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
                  <option value="">{tl.noneOption}</option>
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
                <label className={styles.fieldLabel}>
                  dataset_tags <span className={styles.fieldHint}>(coma-separados)</span>
                </label>
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

            {/* Capture actions */}
            <div className={styles.actionsRow}>
              <button className={`${styles.btn} ${styles.btnCyan}`} onClick={handleSave} disabled={busy}>
                {saving ? '…' : tl.save}
              </button>
              <button className={`${styles.btn} ${styles.btnMagenta}`} onClick={handleDisable} disabled={busy || !isActive}>
                {tl.disable}
              </button>
              <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={() => void reloadCapture()} disabled={busy}>
                {tl.reload}
              </button>
              <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={handleRestorePersonality} disabled={busy}>
                {tl.restorePersonality}
              </button>
            </div>

            {/* Dataset stats */}
            <DatasetStatsSection stats={datasetStats} loading={debugLoading} />
          </>
        )}

        {/* ── Debug tab ── */}
        {tab === 'debug' && (
          <>
            {debugError && <p className={styles.errorMsg}>{debugError}</p>}
            {debugLoading && recentEvents.length === 0 && <p className={styles.loading}>Cargando traza…</p>}

            <div className={styles.section}>
              <div className={styles.sectionRow}>
                <p className={styles.sectionLabel}>Última traza</p>
                <button className={`${styles.btn} ${styles.btnSecondary}`} onClick={() => void reloadDebug()} disabled={debugLoading}>
                  Refrescar
                </button>
              </div>
              <div className={styles.traceIdLabel}>{lastTraceId ?? 'Sin trace_id todavía'}</div>
            </div>

            {lastTraceEvents.length === 0 && !debugLoading && (
              <p className={`${styles.loading} ${styles.emptyMsg}`}>No hay eventos para esta traza.</p>
            )}
            {lastTraceEvents.map((ev, i) => <EventCard key={`${ev.timestamp}-${i}`} event={ev} />)}

            {recentEvents.length > 0 && (
              <>
                <div className={styles.section} style={{ marginTop: 8 }}>
                  <p className={styles.sectionLabel}>Eventos recientes ({recentEvents.length})</p>
                </div>
                {recentEvents.map((ev, i) => <EventCard key={`r-${ev.timestamp}-${i}`} event={ev} />)}
              </>
            )}
          </>
        )}

      </div>

      <HelpModal open={helpOpen} onClose={() => setHelpOpen(false)} title="Dev Tools">
        <p><strong>Dataset</strong> — configura la captura de conversaciones para el dataset LoRA y consulta estadísticas del dataset actual.</p>
        <p><strong>Debug</strong> — muestra la última traza de eventos del backend y los eventos recientes del sistema.</p>
        <p><strong>dataset_source</strong> — tipo de sesión. Define cómo se agrupa este dato en la exportación.</p>
        <p><strong>speaker_source</strong> — indica si el input viene de una persona o de Claude.</p>
        <p><strong>dataset_eligible</strong> — si este par entra en el pool de candidatos para fine-tuning.</p>
        <p>Solo visible para admin.</p>
      </HelpModal>
    </div>
  );
}
