import { AnimatePresence, motion } from 'framer-motion';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './FontPicker.module.css';

type FontKey = 'orbitron' | 'sharetech' | 'rajdhani';

const FONTS: Array<{ key: FontKey; name: string; family: string; labelKey: 'fontFuturistic' | 'fontTerminal' | 'fontElegant' }> = [
  { key: 'orbitron',   name: 'Orbitron',       family: "'Orbitron', sans-serif",         labelKey: 'fontFuturistic' },
  { key: 'sharetech',  name: 'Share Tech Mono', family: "'Share Tech Mono', monospace",  labelKey: 'fontTerminal'   },
  { key: 'rajdhani',   name: 'Rajdhani',        family: "'Rajdhani', sans-serif",         labelKey: 'fontElegant'   },
];

interface FontPickerProps {
  open: boolean;
  activeFont: FontKey;
  onClose: () => void;
  onSelect: (key: FontKey) => void;
  uiLang?: UiLang;
}

export function FontPicker({ open, activeFont, onClose, onSelect, uiLang = 'es' }: FontPickerProps) {
  const tl = TRANSLATIONS[uiLang].chat;

  const handleSelect = (key: FontKey) => {
    document.documentElement.setAttribute('data-font', key);
    localStorage.setItem('sity_font', key);
    onSelect(key);
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className={styles.backdrop}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
        >
          <motion.div
            className={styles.sheet}
            initial={{ opacity: 0, y: 40 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 40 }}
            transition={{ duration: 0.22, ease: 'easeOut' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className={styles.handle} />
            <h3 className={styles.title}>{tl.changeFont}</h3>

            <div className={styles.optionList}>
              {FONTS.map(({ key, name, family, labelKey }) => (
                <button
                  key={key}
                  className={`${styles.option} ${activeFont === key ? styles.optionActive : ''}`}
                  onClick={() => handleSelect(key)}
                >
                  <span className={styles.fontName} style={{ fontFamily: family }}>{name}</span>
                  <span className={styles.fontLabel}>{tl[labelKey]}</span>
                </button>
              ))}
            </div>

            <button className={styles.cancelBtn} onClick={onClose}>{tl.fontCancel}</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
