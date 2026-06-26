import { AnimatePresence, motion } from 'framer-motion';
import styles from './FontPicker.module.css';

type FontKey = 'orbitron' | 'sharetech' | 'rajdhani';

const FONTS: Array<{ key: FontKey; name: string; label: string; family: string }> = [
  { key: 'orbitron',   name: 'Orbitron',        label: 'Futurista', family: "'Orbitron', sans-serif" },
  { key: 'sharetech',  name: 'Share Tech Mono',  label: 'Terminal',  family: "'Share Tech Mono', monospace" },
  { key: 'rajdhani',   name: 'Rajdhani',         label: 'Elegante',  family: "'Rajdhani', sans-serif" },
];

interface FontPickerProps {
  open: boolean;
  activeFont: FontKey;
  onClose: () => void;
  onSelect: (key: FontKey) => void;
}

export function FontPicker({ open, activeFont, onClose, onSelect }: FontPickerProps) {
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
            <h3 className={styles.title}>Cambiar fuente</h3>

            <div className={styles.optionList}>
              {FONTS.map(({ key, name, label, family }) => (
                <button
                  key={key}
                  className={`${styles.option} ${activeFont === key ? styles.optionActive : ''}`}
                  onClick={() => handleSelect(key)}
                >
                  <span className={styles.fontName} style={{ fontFamily: family }}>{name}</span>
                  <span className={styles.fontLabel}>{label}</span>
                </button>
              ))}
            </div>

            <button className={styles.cancelBtn} onClick={onClose}>Cancelar</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
