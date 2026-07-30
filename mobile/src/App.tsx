import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useChat } from './hooks/useChat';
import { useAuth } from './hooks/useAuth';
import { BottomNav } from './components/BottomNav';
import { ChatScreen } from './screens/ChatScreen';
import { PersonalityScreen } from './screens/PersonalityScreen';
import { VoiceScreen } from './screens/VoiceScreen';
import { DatasetScreen } from './screens/DatasetScreen';
import { LoginScreen } from './screens/LoginScreen';
import { RegisterScreen } from './screens/RegisterScreen';
import styles from './App.module.css';

export type Screen = 'chat' | 'personality' | 'voice' | 'dataset';
type AuthView = 'login' | 'register';

const screenVariants = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -16 },
};

export default function App() {
  const [activeScreen, setActiveScreen] = useState<Screen>('chat');
  const [authView, setAuthView] = useState<AuthView>('login');
  const auth = useAuth();
  const chat = useChat();

  // null = still resolving session from /auth/me — show nothing to avoid flash
  if (auth.currentUser === null) {
    return (
      <div className={styles.app} style={{ alignItems: 'center', justifyContent: 'center' }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          color: 'var(--text-secondary)',
          letterSpacing: '0.1em',
        }}>
          Inicializando…
        </span>
      </div>
    );
  }

  // Guest who has never actively chosen to continue as guest → show auth screens
  const guestOptedIn = sessionStorage.getItem('sity_guest_opted_in') === 'true';
  const isGuest = auth.currentUser.role === 'guest';
  const showAuth = isGuest && !guestOptedIn;

  if (showAuth) {
    return (
      <div className={styles.app}>
        <AnimatePresence mode="wait">
          <motion.div
            key={authView}
            style={{ height: '100%', overflowY: 'auto' }}
            variants={screenVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {authView === 'login' ? (
              <LoginScreen
                auth={auth}
                onSwitchToRegister={() => setAuthView('register')}
              />
            ) : (
              <RegisterScreen
                auth={auth}
                onSwitchToLogin={() => setAuthView('login')}
              />
            )}
          </motion.div>
        </AnimatePresence>
      </div>
    );
  }

  // Authenticated user or guest who chose to skip login → show full app
  function renderScreen(screen: Screen) {
    switch (screen) {
      case 'chat':        return <ChatScreen {...chat} />;
      case 'personality': return <PersonalityScreen />;
      case 'voice':       return <VoiceScreen />;
      case 'dataset':     return <DatasetScreen />;
    }
  }

  return (
    <div className={styles.app}>
      <main className={styles.screenContainer}>
        <AnimatePresence mode="wait">
          <motion.div
            key={activeScreen}
            className={styles.screenWrapper}
            variants={screenVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {renderScreen(activeScreen)}
          </motion.div>
        </AnimatePresence>
      </main>
      <BottomNav active={activeScreen} onNavigate={setActiveScreen} />
    </div>
  );
}
