import { memo } from 'react';
import type { PersonalitySettings } from '../hooks/usePersonality';
import { NeonSlider } from './NeonSlider';
import styles from './PersonalitySliderItem.module.css';

// ── Parameter icons ───────────────────────────────────────────────────────────

function IconSarcasm()    { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><circle cx="9" cy="10" r="1" fill="currentColor"/><circle cx="15" cy="10" r="1" fill="currentColor"/><path d="M9 14s1-1 3-1 3 1 3 1"/></svg>; }
function IconRudeness()   { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4"/><path d="M6 14 4 22h16l-2-8"/><line x1="12" y1="12" x2="12" y2="14"/></svg>; }
function IconWarmth()     { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 21.593c-5.63-5.539-11-10.297-11-14.402C1 3.534 3.938 1 7 1c1.961 0 3.815.83 5 2.18C13.185 1.83 15.04 1 17 1c3.062 0 6 2.534 6 6.191 0 4.105-5.37 8.863-11 14.402z"/></svg>; }
function IconHonesty()    { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>; }
function IconInitiative() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>; }
function IconHumor()      { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>; }
function IconColdness()   { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><line x1="12" y1="2" x2="12" y2="22"/><path d="m20 6-8 6-8-6"/><path d="m20 18-8-6-8 6"/><path d="m2 12 10 0"/><path d="m12 12 10 0"/></svg>; }
function IconContrarian() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="m7 16 4-4-4-4"/><path d="m17 8-4 4 4 4"/></svg>; }
function IconPatience()   { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M5 3h14"/><path d="m17 3-5 9-5-9"/><path d="M5 21h14"/><path d="m7 21 5-9 5 9"/></svg>; }
function IconRefusal()    { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>; }
function IconHelp()       { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/></svg>; }
function IconVerbosity()  { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="17" y2="12"/><line x1="3" y1="18" x2="13" y2="18"/></svg>; }
function IconMelancholy() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z"/></svg>; }
function IconSkepticism() { return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/><line x1="3" y1="3" x2="21" y2="21"/></svg>; }

type K = keyof PersonalitySettings;

interface ParamMeta {
  jp: string;
  es: string;
  Icon: React.FC;
}

export const PARAM_META: Record<K, ParamMeta> = {
  sarcasm_level:          { jp: '皮肉',    es: 'Sarcasmo',     Icon: IconSarcasm    },
  rudeness_level:         { jp: '毒舌',    es: 'Mala leche',   Icon: IconRudeness   },
  warmth_level:           { jp: '温かさ',  es: 'Calidez',      Icon: IconWarmth     },
  honesty_level:          { jp: '正直',    es: 'Honestidad',   Icon: IconHonesty    },
  initiative_level:       { jp: '積極性',  es: 'Iniciativa',   Icon: IconInitiative },
  dry_humor_level:        { jp: 'ユーモア', es: 'Humor seco',  Icon: IconHumor      },
  frialdad_afectiva_level:{ jp: '冷淡さ',  es: 'Frialdad',     Icon: IconColdness   },
  contrarian_level:       { jp: '反論',    es: 'Contradicción',Icon: IconContrarian },
  patience_level:         { jp: '忍耐',    es: 'Paciencia',    Icon: IconPatience   },
  refusal_chance:         { jp: '拒否',    es: 'Negación',     Icon: IconRefusal    },
  helpfulness_level:      { jp: '親切',    es: 'Ayuda',        Icon: IconHelp       },
  verbosity_level:        { jp: '冗長',    es: 'Verbosidad',   Icon: IconVerbosity  },
  melancholy_level:       { jp: '憂鬱',    es: 'Melancolía',   Icon: IconMelancholy },
  skepticism_level:       { jp: '懐疑',    es: 'Escepticismo', Icon: IconSkepticism },
};

// ── Slider item ───────────────────────────────────────────────────────────────

interface PersonalitySliderItemProps {
  paramKey: K;
  value: number; // 0–1
  onDrag: (v: number) => void;
  onCommit: (v: number) => void;
}

export const PersonalitySliderItem = memo(function PersonalitySliderItem({
  paramKey, value, onDrag, onCommit,
}: PersonalitySliderItemProps) {
  const { jp, es, Icon } = PARAM_META[paramKey];
  const pct = Math.round(value * 100);

  return (
    <div className={styles.row}>
      <span className={styles.icon}><Icon /></span>

      <div className={styles.names}>
        <span className={styles.nameJp}>{jp}</span>
        <span className={styles.nameEs}>{es}</span>
      </div>

      <div className={styles.sliderWrap}>
        <NeonSlider value={value} onChange={onDrag} onCommit={onCommit} />
      </div>

      <span className={styles.pct}>{pct}%</span>
    </div>
  );
});
