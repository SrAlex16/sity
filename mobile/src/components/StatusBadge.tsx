import { motion } from 'framer-motion';
import type { ChatStatus } from '../hooks/useChat';
import styles from './StatusBadge.module.css';

const CONFIG: Record<ChatStatus, { label: string; cls: string }> = {
  conectado:    { label: 'EN LÍNEA',      cls: 'dotCyan' },
  procesando:   { label: 'PROCESANDO...', cls: 'dotMagenta' },
  desconectado: { label: 'DESCONECTADO',  cls: 'dotRed' },
};

interface StatusBadgeProps {
  status: ChatStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const { label, cls } = CONFIG[status];
  const pulsing = status === 'procesando';

  return (
    <div className={styles.badge}>
      <motion.span
        className={`${styles.dot} ${styles[cls as keyof typeof styles]}`}
        animate={pulsing ? { opacity: [1, 0.25, 1] } : { opacity: 1 }}
        transition={pulsing ? { repeat: Infinity, duration: 0.75, ease: 'easeInOut' } : undefined}
      />
      <span className={styles.label}>{label}</span>
    </div>
  );
}
