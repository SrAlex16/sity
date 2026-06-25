import { motion } from 'framer-motion';
import styles from './TypingIndicator.module.css';

export function TypingIndicator() {
  return (
    <div className={styles.wrapper}>
      <div className={styles.bubble}>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className={styles.dot}
            animate={{ y: [0, -5, 0] }}
            transition={{ repeat: Infinity, duration: 0.7, delay: i * 0.15, ease: 'easeInOut' }}
          />
        ))}
      </div>
    </div>
  );
}
