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

const _ADMIN_SCREENS = new Set<Screen>(['voice', 'dataset']);

function AccessDenied() {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      justifyContent: 'center', height: '100%', gap: '0.75rem',
      fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)',
      fontSize: '0.8rem', letterSpacing: '0.05em', textAlign: 'center',
      padding: '2rem',
    }}>
      <span style={{ fontSize: '2rem', opacity: 0.3 }}>[ acceso denegado ]</span>
      <span>Esta sección requiere permisos de administrador.</span>
    </div>
  );
}

const screenVariants = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -16 },
};

export default function App() {
  const [activeScreen, setActiveScreen] = useState<Screen>('chat');
  const [authView, setAuthView] = useState<AuthView>('login');
  const auth = useAuth();

  // Detect /reset-password?token=XXX on first load. Clean the URL immediately so
  // the token never lingers in the address bar, history, or clipboard.
  const [initialResetToken, setInitialResetToken] = useState<string | null>(() => {
    if (window.location.pathname === '/reset-password') {
      const token = new URLSearchParams(window.location.search).get('token');
      if (token) {
        window.history.replaceState({}, '', '/');
        return token;
      }
    }
    return null;
  });
  const userKey = auth.currentUser == null
    ? null
    : auth.currentUser.role === 'guest'
      ? 'guest'
      : `user:${auth.currentUser.id}`;
  const chat = useChat(userKey);

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
  const isGuest = auth.currentUser.role === 'guest';
  const showAuth = isGuest && !auth.guestOptedIn;

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
                initialResetToken={initialResetToken}
                onResetTokenConsumed={() => setInitialResetToken(null)}
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

  const role = auth.currentUser.role;
  const isAdmin = role === 'admin';

  // If the user's role dropped below admin while on a restricted screen
  // (e.g. logout while on VoiceScreen), fall back to chat silently.
  const effectiveScreen: Screen =
    _ADMIN_SCREENS.has(activeScreen) && !isAdmin ? 'chat' : activeScreen;

  // Authenticated user or guest who chose to skip login → show full app
  function renderScreen(screen: Screen) {
    // Defense-in-depth: even if a restricted tab is somehow reachable,
    // never render its content for non-admin callers.
    if (_ADMIN_SCREENS.has(screen) && !isAdmin) return <AccessDenied />;
    switch (screen) {
      case 'chat':        return <ChatScreen {...chat} onLogout={auth.logout} currentUser={auth.currentUser} />;
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
            key={effectiveScreen}
            className={styles.screenWrapper}
            variants={screenVariants}
            initial="initial"
            animate="animate"
            exit="exit"
            transition={{ duration: 0.18, ease: 'easeOut' }}
          >
            {renderScreen(effectiveScreen)}
          </motion.div>
        </AnimatePresence>
      </main>
      <BottomNav active={effectiveScreen} onNavigate={setActiveScreen} role={role} />
    </div>
  );
}
