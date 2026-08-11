import { useState, useCallback } from 'react';
import { motion } from 'framer-motion';
import { usePersonality } from '../hooks/usePersonality';
import type { PersonalitySettings } from '../hooks/usePersonality';
import { MoodFace } from '../components/MoodFace';
import { PersonalitySliderItem, PARAM_META } from '../components/PersonalitySliderItem';
import { HelpModal } from '../components/HelpModal';
import { AltersPanel } from '../components/AltersPanel';
import styles from './PersonalityScreen.module.css';

function computeMoodLevel(s: PersonalitySettings): number {
  return Math.round(
    (s.rudeness_level  * 0.4 +
     s.sarcasm_level   * 0.3 +
     s.contrarian_level * 0.2 +
     s.dry_humor_level * 0.1) * 100
  );
}

function moodLabel(pct: number): string {
  if (pct <= 20) return 'Tranquila';
  if (pct <= 40) return 'Neutral';
  if (pct <= 60) return 'Irritable';
  if (pct <= 80) return 'Hostil';
  return 'Nuclear';
}

function moodColor(pct: number): string {
  if (pct <= 25) return '#00f5ff';
  if (pct <= 50) return '#00ff80';
  if (pct <= 75) return '#ff8000';
  return '#ff00ff';
}

const PARAM_ORDER = Object.keys(PARAM_META) as (keyof PersonalitySettings)[];

interface PersonalityScreenProps {
  role: string;
}

export function PersonalityScreen({ role }: PersonalityScreenProps) {
  const isGuest = role === 'guest';
  const { settings, isLoading, adjust, reset, reload } = usePersonality();
  const [liveOverride, setLiveOverride] = useState<Partial<PersonalitySettings>>({});
  const [helpOpen, setHelpOpen] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [view, setView] = useState<'params' | 'alters'>('params');

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
            Rasgos
          </button>
          <button
            className={`${styles.viewTab} ${view === 'alters' ? styles.viewTabActive : ''}`}
            onClick={() => setView('alters')}
          >
            Alters
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
                  {resetting ? '…' : 'Restaurar'}
                </button>
                <button
                  className={styles.actionBtn}
                  onClick={() => void reload()}
                  disabled={isLoading}
                >
                  {isLoading ? '…' : 'Recargar'}
                </button>
              </div>
            </div>
          ) : (
            <div className={styles.loadingCard}>
              {isLoading ? 'Cargando…' : 'Sin datos'}
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
          </div>
        </>
      )}

      {/* Alters view — User/Admin only */}
      {view === 'alters' && !isGuest && (
        <div className={styles.altersView}>
          <AltersPanel onLoaded={handleAlterLoaded} />
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
        <p>La cara refleja el nivel de <em>encabronamiento</em> calculado a partir de rudeza, sarcasmo, contrariedad y humor seco.</p>
        <p><strong>Restaurar</strong> vuelve a los valores predeterminados del perfil activo.</p>
        <p><strong>Alters</strong> (pestaña) permite guardar y cargar presets completos de personalidad.</p>
      </HelpModal>
    </div>
  );
}
