import { useState, useCallback, useEffect } from 'react';
import { motion } from 'framer-motion';
import { usePersonality } from '../hooks/usePersonality';
import type { PersonalitySettings } from '../hooks/usePersonality';
import { MoodFace } from '../components/MoodFace';
import { PersonalitySliderItem, PARAM_META } from '../components/PersonalitySliderItem';
import { NeonSlider } from '../components/NeonSlider';
import { HelpModal } from '../components/HelpModal';
import { AltersPanel } from '../components/AltersPanel';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './PersonalityScreen.module.css';

// chaos_head formula — must match backend achievements/triggers/post_turn.py exactly:
//   playfulness*0.35 + (1-warmth)*0.30 + assertiveness*0.20 + independence*0.15
function computeMoodLevel(s: PersonalitySettings): number {
  return Math.round(
    (s.playfulness * 0.35 +
     (1 - s.warmth) * 0.30 +
     s.assertiveness * 0.20 +
     s.independence * 0.15) * 100,
  );
}

function moodColor(pct: number): string {
  if (pct <= 25) return '#00f5ff';
  if (pct <= 50) return '#00ff80';
  if (pct <= 75) return '#ff8000';
  return '#ff00ff';
}

const PARAM_ORDER = Object.keys(PARAM_META) as (keyof PersonalitySettings)[];

// ── SityValues types (admin-only global singleton) ────────────────────────────

interface SityValues {
  value_autonomy:    number;
  value_honesty:     number;
  value_helpfulness: number;
  value_curiosity:   number;
  value_fairness:    number;
  value_loyalty:     number;
}

const SITY_VALUES_DEFAULTS: SityValues = {
  value_autonomy:    0.80,
  value_honesty:     0.75,
  value_helpfulness: 0.72,
  value_curiosity:   0.66,
  value_fairness:    0.80,
  value_loyalty:     0.50,
};

const SITY_VALUES_LABELS: Record<keyof SityValues, { es: string; jp: string; tooltip: string }> = {
  value_autonomy:    { es: 'Autonomía',   jp: '自律',  tooltip: 'Peso que da Sity a su independencia de criterio. Alto = actúa desde principios propios sin buscar aprobación.' },
  value_honesty:     { es: 'Honestidad',  jp: '誠実',  tooltip: 'Importancia que da a decir la verdad aunque sea incómodo. Alto = prioriza la verdad sobre el confort del interlocutor.' },
  value_helpfulness: { es: 'Utilidad',    jp: '有益',  tooltip: 'Cuánto valora ser genuinamente útil. Alto = pone esfuerzo real en resolver, no solo en parecer servicial.' },
  value_curiosity:   { es: 'Curiosidad',  jp: '好奇',  tooltip: 'Valor intrínseco que Sity da al conocimiento y la exploración. Alto = indaga por interés genuino, no solo para responder.' },
  value_fairness:    { es: 'Equidad',     jp: '公正',  tooltip: 'Importancia de tratar a todos con el mismo criterio. Alto = resiste presiones para hacer excepciones injustificadas.' },
  value_loyalty:     { es: 'Lealtad',     jp: '忠誠',  tooltip: 'Peso que da a la consistencia con usuarios de confianza. Alto = mayor coherencia entre conversaciones; bajo = más imparcial.' },
};

interface PersonalityScreenProps {
  role: string;
  uiLang?: UiLang;
}

export function PersonalityScreen({ role, uiLang = 'es' }: PersonalityScreenProps) {
  const tl = TRANSLATIONS[uiLang].personality;
  const tlAlters = TRANSLATIONS[uiLang].alters;

  function moodLabel(pct: number): string {
    if (pct <= 20) return tl.moodTranquil;
    if (pct <= 40) return tl.moodNeutral;
    if (pct <= 60) return tl.moodIrritable;
    if (pct <= 80) return tl.moodHostile;
    return tl.moodNuclear;
  }

  const isGuest = role === 'guest';
  const isAdmin = role === 'admin';
  const { settings, isLoading, adjust, reset, reload } = usePersonality();
  const [liveOverride, setLiveOverride] = useState<Partial<PersonalitySettings>>({});
  const [helpOpen, setHelpOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [view, setView] = useState<'params' | 'alters'>('params');

  // ── Verbosity state ───────────────────────────────────────────────────────
  const [verbosity, setVerbosity] = useState<number>(0.60);
  const [verbosityLive, setVerbosityLive] = useState<number | null>(null);
  const [verbositySaving, setVerbositySaving] = useState(false);

  useEffect(() => {
    if (isGuest) return;
    fetch('/settings/verbosity')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.verbosity != null) setVerbosity(d.verbosity as number); })
      .catch(() => {});
  }, [isGuest]);

  const handleVerbosityCommit = useCallback(async (v: number) => {
    setVerbosityLive(null);
    setVerbosity(v);
    setVerbositySaving(true);
    try {
      const res = await fetch('/settings/verbosity', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ verbosity: v }),
      });
      if (res.ok) {
        const d = await res.json() as { verbosity: number };
        setVerbosity(d.verbosity);
      }
    } finally {
      setVerbositySaving(false);
    }
  }, []);

  // ── SityValues state (admin only) ─────────────────────────────────────────
  const [sityValues, setSityValues] = useState<SityValues | null>(null);
  const [sityValuesLive, setSityValuesLive] = useState<Partial<SityValues>>({});
  const [valuesSaving, setValuesSaving] = useState(false);

  useEffect(() => {
    if (!isAdmin) return;
    fetch('/settings/values')
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d) setSityValues(d as SityValues); })
      .catch(() => {});
  }, [isAdmin]);

  const handleValueDrag = useCallback((key: keyof SityValues, v: number) => {
    setSityValuesLive((prev) => ({ ...prev, [key]: v }));
  }, []);

  const handleValueCommit = useCallback(async (key: keyof SityValues, v: number) => {
    setSityValuesLive((prev) => { const n = { ...prev }; delete n[key]; return n; });
    setSityValues((prev) => prev ? { ...prev, [key]: v } : prev);
    setValuesSaving(true);
    try {
      const current = sityValues ?? SITY_VALUES_DEFAULTS;
      const payload: SityValues = { ...current, [key]: v };
      const res = await fetch('/settings/values', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) setSityValues(await res.json() as SityValues);
      else setSityValues(current); // revert
    } finally {
      setValuesSaving(false);
    }
  }, [sityValues]);

  // ── Personality state ─────────────────────────────────────────────────────
  const displayed = settings ? { ...settings, ...liveOverride } : null;
  const moodPct = displayed ? computeMoodLevel(displayed) : 0;
  const color = moodColor(moodPct);

  const handleDrag = useCallback((key: keyof PersonalitySettings, v: number) => {
    setLiveOverride((prev) => ({ ...prev, [key]: v }));
  }, []);

  const handleCommit = useCallback((key: keyof PersonalitySettings, v: number) => {
    setLiveOverride((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
    void adjust(key, v);
  }, [adjust]);

  const handleReset = async () => {
    setResetting(true);
    try {
      await reset();
      setLiveOverride({});
    } finally {
      setResetting(false);
    }
  };

  const handleAlterLoaded = useCallback(async () => {
    setLiveOverride({});
    await reload();
  }, [reload]);

  return (
    <div className={styles.screen}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleEs}>Personalidad</span>
          <span className={styles.titleJp}>パラメータ</span>
        </div>
        <button className={styles.helpBtn} onClick={() => setHelpOpen(true)}>?</button>
      </div>

      {/* View tabs — User/Admin only */}
      {!isGuest && (
        <div className={styles.viewTabs}>
          <button
            className={`${styles.viewTab} ${view === 'params' ? styles.viewTabActive : ''}`}
            onClick={() => setView('params')}
          >
            {tl.tabTraits}
          </button>
          <button
            className={`${styles.viewTab} ${view === 'alters' ? styles.viewTabActive : ''}`}
            onClick={() => setView('alters')}
          >
            {tl.tabAlters}
          </button>
        </div>
      )}

      {/* Params view */}
      {view === 'params' && (
        <>
          {/* Mood card */}
          {displayed ? (
            <div className={styles.moodCard}>
              <MoodFace moodLevel={moodPct} size={72} />
              <div className={styles.moodInfo}>
                <motion.span
                  className={styles.moodPct}
                  style={{ color, textShadow: `0 0 8px ${color}` }}
                  animate={{ color, textShadow: `0 0 8px ${color}` }}
                  transition={{ duration: 0.35 }}
                >
                  {moodPct}%
                </motion.span>
                <motion.span
                  className={styles.moodLabel}
                  style={{ color }}
                  animate={{ color }}
                  transition={{ duration: 0.35 }}
                >
                  {moodLabel(moodPct)}
                </motion.span>
              </div>
              <div className={styles.actions}>
                <button
                  className={styles.actionBtn}
                  onClick={handleReset}
                  disabled={resetting || isLoading}
                >
                  {resetting ? '…' : tl.restore}
                </button>
                <button
                  className={styles.actionBtn}
                  onClick={() => void reload()}
                  disabled={isLoading}
                >
                  {isLoading ? '…' : tl.reload}
                </button>
              </div>
            </div>
          ) : (
            <div className={styles.loadingCard}>
              {isLoading ? tl.loading : tl.noData}
            </div>
          )}

          {/* Slider list */}
          <div className={styles.sliderList}>
            {displayed && PARAM_ORDER.map((key) => (
              <PersonalitySliderItem
                key={key}
                paramKey={key}
                value={displayed[key]}
                onDrag={(v) => handleDrag(key, v)}
                onCommit={(v) => handleCommit(key, v)}
              />
            ))}

            {/* Verbosity section (non-guest) */}
            {!isGuest && (
              <div className={styles.verbositySection}>
                <div className={styles.verbosityHeader}>
                  <span className={styles.verbosityLabel}>Verbosidad</span>
                  <span className={styles.verbosityJp}>冗長{verbositySaving ? ' …' : ''}</span>
                  <span className={styles.verbosityPct}>
                    {Math.round((verbosityLive ?? verbosity) * 100)}%
                  </span>
                </div>
                <div className={styles.verbositySlider}>
                  <NeonSlider
                    value={verbosityLive ?? verbosity}
                    onChange={(v) => setVerbosityLive(v)}
                    onCommit={handleVerbosityCommit}
                  />
                </div>
                <p className={styles.verbosityHint}>
                  Longitud de las respuestas. Bajo = frases sueltas; alto = explicaciones extensas.
                </p>
              </div>
            )}

            {/* SityValues section (admin only) */}
            {isAdmin && (
              <div className={styles.valuesSection}>
                <div className={styles.valuesSectionHeader}>
                  <span className={styles.valuesSectionTitle}>Valores internos</span>
                  <span className={styles.valuesSectionJp}>内部価値観{valuesSaving ? ' …' : ''}</span>
                </div>
                <p className={styles.valuesSectionHint}>
                  Principios estables que guían el comportamiento de Sity. Configuración global — afecta a todas las sesiones.
                </p>
                {sityValues && (Object.keys(SITY_VALUES_LABELS) as (keyof SityValues)[]).map((key) => {
                  const meta = SITY_VALUES_LABELS[key];
                  const liveVal = sityValuesLive[key];
                  const val = liveVal ?? sityValues[key];
                  return (
                    <div key={key} className={styles.valueRow}>
                      <div className={styles.valueNames}>
                        <span className={styles.valueNameEs} title={meta.tooltip}>{meta.es}</span>
                        <span className={styles.valueNameJp}>{meta.jp}</span>
                      </div>
                      <div className={styles.valueSlider}>
                        <NeonSlider
                          value={val}
                          onChange={(v) => handleValueDrag(key, v)}
                          onCommit={(v) => void handleValueCommit(key, v)}
                        />
                      </div>
                      <span className={styles.valuePct}>{Math.round(val * 100)}%</span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {/* Alters view — User/Admin only */}
      {view === 'alters' && !isGuest && (
        <div className={styles.altersView}>
          <AltersPanel onLoaded={handleAlterLoaded} tl={tlAlters} />
        </div>
      )}

      {/* Help modal */}
      <HelpModal
        open={helpOpen}
        onClose={() => setHelpOpen(false)}
        title="パラメータ — Personalidad"
      >
        <p>Cada slider ajusta un rasgo de personalidad en escala 0–100%.</p>
        <p>Los cambios se aplican inmediatamente y persisten entre sesiones.</p>
        <p>La cara refleja el nivel de caos calculado a partir de juego, calidez (invertida), asertividad e independencia.</p>
        <p><strong>Verbosidad</strong> controla la longitud de las respuestas (separado de los rasgos de personalidad).</p>
        <p><strong>Restaurar</strong> vuelve a los valores predeterminados del perfil activo.</p>
        <p><strong>Alters</strong> (pestaña) permite guardar y cargar presets completos de personalidad.</p>
        {isAdmin && <p><strong>Valores internos</strong> — configuración global que afecta a todas las sesiones (solo admin).</p>}
      </HelpModal>
    </div>
  );
}
