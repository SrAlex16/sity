import { useState, useEffect } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useAchievements } from '../hooks/useAchievements';
import type { Achievement } from '../hooks/useAchievements';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './AchievementsScreen.module.css';

const CATEGORY_ORDER = ['personalidad', 'tools', 'memoria', 'domotica', 'background', 'secretos'];
const REDACT_NAME = '████████████';
const REDACT_DESC = '████████';

interface AchievementsScreenProps {
  role: string;
  uiLang?: UiLang;
}

function formatDate(iso: string, uiLang: UiLang): string {
  const d = new Date(iso);
  if (uiLang === 'ja') {
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
  }
  const months = uiLang === 'es'
    ? ['ene','feb','mar','abr','may','jun','jul','ago','sep','oct','nov','dic']
    : ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  return `${d.getDate()} ${months[d.getMonth()]} ${d.getFullYear()}`;
}

function TrophyIcon() {
  return (
    <svg className={styles.trophyIcon} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H3V5h3" />
      <path d="M18 9h3V5h-3" />
      <path d="M6 5h12v7a6 6 0 0 1-12 0V5Z" />
      <line x1="12" y1="17" x2="12" y2="21" />
      <line x1="8" y1="21" x2="16" y2="21" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg className={styles.lockIcon} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
      <path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  );
}

function AchievementCard({ achievement, uiLang }: { achievement: Achievement; uiLang: UiLang }) {
  const [hintOpen, setHintOpen] = useState(false);
  const isSecret = achievement.category === 'secretos';
  const { unlocked, name, description, unlocked_at } = achievement;

  if (unlocked) {
    return (
      <div className={`${styles.card} ${styles.cardUnlocked}`}>
        <div className={styles.cardIcon}><TrophyIcon /></div>
        <div className={styles.cardBody}>
          <span className={styles.cardName}>{name}</span>
          <span className={styles.cardDesc}>{description}</span>
          {unlocked_at && (
            <span className={styles.cardDate}>{formatDate(unlocked_at, uiLang)}</span>
          )}
        </div>
      </div>
    );
  }

  if (isSecret) {
    return (
      <div className={`${styles.card} ${styles.cardLocked}`}>
        <div className={styles.cardIcon}><LockIcon /></div>
        <div className={styles.cardBody}>
          <span className={`${styles.cardName} ${styles.redacted}`}>{REDACT_NAME}</span>
          <span className={`${styles.cardDesc} ${styles.redacted}`}>{REDACT_DESC}</span>
        </div>
      </div>
    );
  }

  return (
    <button
      className={`${styles.card} ${styles.cardLocked} ${styles.cardTappable}`}
      onClick={() => setHintOpen(o => !o)}
    >
      <div className={styles.cardIcon}><LockIcon /></div>
      <div className={styles.cardBody}>
        <span className={styles.cardName}>{name}</span>
        {hintOpen && <span className={styles.cardHint}>{description}</span>}
      </div>
    </button>
  );
}

function playUnlockSound() {
  try {
    const ctx = new AudioContext();
    const gain = ctx.createGain();
    gain.connect(ctx.destination);
    gain.gain.setValueAtTime(0.15, ctx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.7);
    // Two-note ascending chime: A5 → D6
    [880, 1174.66].forEach((freq, i) => {
      const osc = ctx.createOscillator();
      osc.connect(gain);
      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, ctx.currentTime + i * 0.18);
      osc.start(ctx.currentTime + i * 0.18);
      osc.stop(ctx.currentTime + i * 0.18 + 0.4);
    });
  } catch {
    // AudioContext unavailable — silent fail
  }
}

function UnlockNotification({ achievement, uiLang, onDismiss }: {
  achievement: Achievement;
  uiLang: UiLang;
  onDismiss: () => void;
}) {
  useEffect(() => { playUnlockSound(); }, []);
  const tl = TRANSLATIONS[uiLang].achievements;
  return (
    <motion.button
      className={styles.notification}
      initial={{ y: 80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      exit={{ y: 80, opacity: 0 }}
      transition={{ type: 'spring', stiffness: 300, damping: 25 }}
      onClick={onDismiss}
    >
      <span className={styles.notifIcon}><TrophyIcon /></span>
      <div className={styles.notifBody}>
        <span className={styles.notifHeader}>{tl.unlocked}</span>
        <span className={styles.notifName}>{achievement.name}</span>
      </div>
    </motion.button>
  );
}

export function AchievementsScreen({ role, uiLang = 'es' }: AchievementsScreenProps) {
  const tl = TRANSLATIONS[uiLang].achievements;
  const isGuest = role === 'guest';
  const { data, isLoading, notification, dismissNotification } = useAchievements();

  const categories = data
    ? CATEGORY_ORDER.filter(cat => data.achievements.some(a => a.category === cat))
    : [];

  const [activeCategory, setActiveCategory] = useState<string>('personalidad');
  const effectiveCategory = categories.includes(activeCategory)
    ? activeCategory
    : (categories[0] ?? 'personalidad');

  const catLabels: Record<string, string> = {
    personalidad: tl.catPersonalidad,
    tools: tl.catTools,
    memoria: tl.catMemoria,
    domotica: tl.catDomotica,
    background: tl.catBackground,
    secretos: tl.catSecrets,
  };

  const visibleAchievements = data
    ? data.achievements.filter(a => a.category === effectiveCategory)
    : [];

  return (
    <div className={styles.screen}>
      {/* Header */}
      <div className={styles.header}>
        <div className={styles.headerText}>
          <span className={styles.titleEs}>{tl.title}</span>
          <span className={styles.titleJp}>実績</span>
        </div>
        {data && (
          <span className={styles.counter}>{data.unlocked_count} / {data.total_count}</span>
        )}
      </div>

      {/* Guest banner */}
      {isGuest && (
        <div className={styles.guestBanner}>{tl.guestBanner}</div>
      )}

      {/* Category tabs */}
      {categories.length > 0 && (
        <div className={styles.tabs}>
          {categories.map(cat => (
            <button
              key={cat}
              className={`${styles.tab} ${effectiveCategory === cat ? styles.tabActive : ''}`}
              onClick={() => setActiveCategory(cat)}
            >
              {catLabels[cat] ?? cat}
            </button>
          ))}
        </div>
      )}

      {/* Achievement grid */}
      <div className={styles.gridWrapper}>
        {isLoading && !data && (
          <div className={styles.loading}>{tl.loading}</div>
        )}
        <div className={styles.grid}>
          {visibleAchievements.map(a => (
            <AchievementCard key={a.slug} achievement={a} uiLang={uiLang} />
          ))}
        </div>
      </div>

      {/* Unlock notification */}
      <AnimatePresence>
        {notification && (
          <UnlockNotification
            key={notification.slug}
            achievement={notification}
            uiLang={uiLang}
            onDismiss={dismissNotification}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
