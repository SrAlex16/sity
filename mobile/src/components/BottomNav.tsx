import { useEffect, useRef } from 'react';
import { motion, useAnimation } from 'framer-motion';
import type { Screen } from '../App';
import styles from './BottomNav.module.css';

interface NavTabProps {
  id: Screen;
  label: string;
  icon: React.FC;
  isActive: boolean;
  onNavigate: (screen: Screen) => void;
}

function NavTab({ id, label, icon: Icon, isActive, onNavigate }: NavTabProps) {
  const controls = useAnimation();
  const wasActive = useRef(false);

  useEffect(() => {
    if (isActive && !wasActive.current) {
      controls.start({ scale: [1, 1.3, 1], transition: { duration: 0.3, ease: 'easeOut' } });
    }
    wasActive.current = isActive;
  }, [isActive, controls]);

  return (
    <button
      className={`${styles.tab} ${isActive ? styles.active : ''}`}
      onClick={() => onNavigate(id)}
      aria-label={label}
    >
      <motion.span className={styles.icon} animate={controls}>
        <Icon />
      </motion.span>
      <span className={styles.label}>{label}</span>
    </button>
  );
}

function IconChat() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    </svg>
  );
}

function IconPersonality() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <line x1="4" y1="6" x2="20" y2="6" />
      <line x1="4" y1="12" x2="20" y2="12" />
      <line x1="4" y1="18" x2="20" y2="18" />
      <circle cx="8" cy="6" r="2.5" fill="currentColor" stroke="none" />
      <circle cx="15" cy="12" r="2.5" fill="currentColor" stroke="none" />
      <circle cx="10" cy="18" r="2.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

function IconVoice() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="23" />
      <line x1="8" y1="23" x2="16" y2="23" />
    </svg>
  );
}

function IconDataset() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  );
}

const TABS: Omit<NavTabProps, 'isActive' | 'onNavigate'>[] = [
  { id: 'chat', label: 'Chat', icon: IconChat },
  { id: 'personality', label: 'Rasgos', icon: IconPersonality },
  { id: 'voice', label: 'Voz', icon: IconVoice },
  { id: 'dataset', label: 'Datos', icon: IconDataset },
];

interface BottomNavProps {
  active: Screen;
  onNavigate: (screen: Screen) => void;
}

export function BottomNav({ active, onNavigate }: BottomNavProps) {
  return (
    <nav className={styles.nav}>
      {TABS.map((tab) => (
        <NavTab
          key={tab.id}
          {...tab}
          isActive={active === tab.id}
          onNavigate={onNavigate}
        />
      ))}
    </nav>
  );
}
