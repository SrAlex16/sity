import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useChat } from './hooks/useChat';
import { useAuth } from './hooks/useAuth';
import { useUiLanguage } from './hooks/useUiLanguage';
import { TRANSLATIONS } from './i18n/translations';
import type { UiLang } from './i18n/translations';
import { BottomNav } from './components/BottomNav';
import { ChatScreen } from './screens/ChatScreen';
import { PersonalityScreen } from './screens/PersonalityScreen';
import { VoiceScreen } from './screens/VoiceScreen';
import { DatasetScreen } from './screens/DatasetScreen';
import { LoginScreen } from './screens/LoginScreen';
import { RegisterScreen } from './screens/RegisterScreen';
import { SharedConversationView } from './screens/SharedConversationView';
import styles from './App.module.css';

// Re-export for components that only need the type
export type { UiLang };

const _screenStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  height: '100%',
  gap: '0.75rem',
  fontFamily: 'var(--font-mono)',
  color: 'var(--text-secondary)',
  fontSize: '0.8rem',
  letterSpacing: '0.05em',
  textAlign: 'center',
  padding: '2rem',
};

export type Screen = 'chat' | 'personality' | 'voice' | 'dataset';
type AuthView = 'login' | 'register';

const _ADMIN_SCREENS = new Set<Screen>(['dataset']);

function AccessDenied({ tl }: { tl: typeof TRANSLATIONS['es'] }) {
  return (
    <div style={_screenStyle}>
      <span style={{ fontSize: '2rem', opacity: 0.3 }}>{tl.app.accessDenied}</span>
      <span>{tl.app.accessDeniedDesc}</span>
    </div>
  );
}

function MaintenanceScreen({ onLogin, tl }: { onLogin: () => void; tl: typeof TRANSLATIONS['es'] }) {
  return (
    <div style={_screenStyle}>
      <span style={{ fontSize: '2rem', opacity: 0.3 }}>{tl.app.maintenance}</span>
      <span>{tl.app.maintenanceDesc}</span>
      <span style={{ opacity: 0.6 }}>{tl.app.maintenanceSub}</span>
      <button
        onClick={onLogin}
        style={{
          marginTop: '1.5rem',
          background: 'none',
          border: '1px solid var(--text-secondary)',
          borderRadius: '4px',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          letterSpacing: '0.05em',
          padding: '0.4rem 0.9rem',
          cursor: 'pointer',
          opacity: 0.6,
        }}
      >
        {tl.app.adminLogin}
      </button>
    </div>
  );
}

const screenVariants = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -16 },
};

// Detect /shared/{id} on first load — render read-only view, bypass auth entirely.
const _sharedIdOnLoad = (() => {
  const m = window.location.pathname.match(/^\/shared\/([a-f0-9]{32})$/);
  return m ? m[1] : null;
})();

export default function App() {
  // Shared conversation route — no auth, no shell, just read-only snapshot.
  if (_sharedIdOnLoad) {
    return <SharedConversationView shareId={_sharedIdOnLoad} />;
  }

  const [activeScreen, setActiveScreen] = useState<Screen>('chat');
  const [authView, setAuthView] = useState<AuthView>('login');
  const [maintenanceShowLogin, setMaintenanceShowLogin] = useState(false);
  const { uiLang, setUiLang } = useUiLanguage();
  const tl = TRANSLATIONS[uiLang];
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

  // Maintenance mode: non-admin users get a clear message + admin login option.
  // Admin is not affected — their /auth/me passes through the middleware.
  if (auth.maintenance && auth.currentUser?.role !== 'admin') {
    if (maintenanceShowLogin) {
      return (
        <div className={styles.app}>
          <LoginScreen
            auth={auth}
            onSwitchToRegister={() => {}}
            initialResetToken={null}
            onResetTokenConsumed={() => {}}
          />
        </div>
      );
    }
    return (
      <div className={styles.app}>
        <MaintenanceScreen onLogin={() => setMaintenanceShowLogin(true)} tl={tl} />
      </div>
    );
  }

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
          {tl.app.initializing}
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
    if (_ADMIN_SCREENS.has(screen) && !isAdmin) return <AccessDenied tl={tl} />;
    switch (screen) {
      case 'chat':        return <ChatScreen {...chat} onLogout={auth.logout} currentUser={auth.currentUser} />;
      case 'personality': return <PersonalityScreen role={role} />;
      case 'voice':       return <VoiceScreen role={role} uiLang={uiLang} onUiLangChange={setUiLang} />;
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
      <BottomNav active={effectiveScreen} onNavigate={setActiveScreen} role={role} uiLang={uiLang} />
    </div>
  );
}
