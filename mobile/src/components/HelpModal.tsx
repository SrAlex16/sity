import { AnimatePresence, motion } from 'framer-motion';
import styles from './HelpModal.module.css';

interface HelpModalProps {
  open: boolean;
  onClose: () => void;
  title?: string;
  children?: React.ReactNode;
}

export function HelpModal({ open, onClose, title = 'Ayuda', children }: HelpModalProps) {
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
            <h2 className={styles.title}>{title}</h2>
            <div className={styles.body}>
              {children ?? <p className={styles.placeholder}>Pendiente de implementar.</p>}
            </div>
            <button className={styles.close} onClick={onClose}>Cerrar</button>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
