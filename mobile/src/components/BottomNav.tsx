import { useEffect, useRef } from 'react';
import { motion, useAnimation } from 'framer-motion';
import type { Screen, UiLang } from '../App';
import { TRANSLATIONS } from '../i18n/translations';
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

function IconSettings() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  );
}

function IconAchievements() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 9H3V5h3" />
      <path d="M18 9h3V5h-3" />
      <path d="M6 5h12v7a6 6 0 0 1-12 0V5Z" />
      <line x1="12" y1="17" x2="12" y2="21" />
      <line x1="8" y1="21" x2="16" y2="21" />
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

const ADMIN_ONLY_TABS = new Set<Screen>(['dataset']);

interface BottomNavProps {
  active: Screen;
  onNavigate: (screen: Screen) => void;
  role: string;
  uiLang: UiLang;
}

export function BottomNav({ active, onNavigate, role, uiLang }: BottomNavProps) {
  const tl = TRANSLATIONS[uiLang].nav;
  const tabs = [
    { id: 'chat' as Screen,         label: tl.chat,         icon: IconChat },
    { id: 'personality' as Screen,  label: tl.personality,  icon: IconPersonality },
    { id: 'achievements' as Screen, label: tl.achievements, icon: IconAchievements },
    { id: 'voice' as Screen,        label: tl.settings,     icon: IconSettings },
    { id: 'dataset' as Screen,      label: tl.dataset,      icon: IconDataset },
  ];
  const visibleTabs = tabs.filter(
    (tab) => !ADMIN_ONLY_TABS.has(tab.id) || role === 'admin',
  );
  return (
    <nav className={styles.nav}>
      {visibleTabs.map((tab) => (
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
