import { AnimatePresence, motion } from 'framer-motion';
import styles from './HelpModal.module.css';

interface HelpModalProps {
  open: boolean;
  onClose: () => void;
}

export function HelpModal({ open, onClose }: HelpModalProps) {
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
            className={styles.modal}
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ duration: 0.2 }}
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className={styles.title}>Ayuda</h2>
            <p className={styles.placeholder}>Pendiente de implementar.</p>
            <button className={styles.close} onClick={onClose}>Cerrar</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
