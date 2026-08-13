import { motion } from 'framer-motion';
import type { ChatStatus } from '../hooks/useChat';
import { TRANSLATIONS } from '../i18n/translations';
import type { UiLang } from '../i18n/translations';
import styles from './StatusBadge.module.css';

const CSS_CLASS: Record<ChatStatus, string> = {
  conectado:    'dotCyan',
  procesando:   'dotMagenta',
  desconectado: 'dotRed',
};

interface StatusBadgeProps {
  status: ChatStatus;
  uiLang?: UiLang;
}

export function StatusBadge({ status, uiLang = 'es' }: StatusBadgeProps) {
  const tl = TRANSLATIONS[uiLang].chat;
  const labels: Record<ChatStatus, string> = {
    conectado:    tl.statusOnline,
    procesando:   tl.statusProcessing,
    desconectado: tl.statusDisconnected,
  };
  const cls = CSS_CLASS[status];
  const pulsing = status === 'procesando';

  return (
    <div className={styles.badge}>
      <motion.span
        className={`${styles.dot} ${styles[cls as keyof typeof styles]}`}
        animate={pulsing ? { opacity: [1, 0.25, 1] } : { opacity: 1 }}
        transition={pulsing ? { repeat: Infinity, duration: 0.75, ease: 'easeInOut' } : undefined}
      />
      <span className={styles.label}>{labels[status]}</span>
    </div>
  );
}
