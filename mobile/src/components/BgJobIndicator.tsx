import { motion, AnimatePresence } from 'framer-motion';
import styles from './BgJobIndicator.module.css';

interface BgJobIndicatorProps {
  active: boolean;
  justFinished: boolean;
}

export function BgJobIndicator({ active, justFinished }: BgJobIndicatorProps) {
  const visible = active || justFinished;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          className={styles.indicator}
          initial={{ opacity: 0, x: -6 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: -6 }}
          transition={{ duration: 0.2 }}
        >
          <motion.span
            className={`${styles.dot} ${justFinished ? styles.dotDone : styles.dotActive}`}
            animate={active && !justFinished ? { opacity: [1, 0.3, 1] } : { opacity: 1 }}
            transition={active && !justFinished ? { repeat: Infinity, duration: 1.2, ease: 'easeInOut' } : undefined}
          />
          <span className={styles.label}>
            {justFinished ? 'LISTO' : 'BG'}
          </span>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
