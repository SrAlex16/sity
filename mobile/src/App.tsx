import { useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { useChat } from './hooks/useChat';
import { BottomNav } from './components/BottomNav';
import { ChatScreen } from './screens/ChatScreen';
import { PersonalityScreen } from './screens/PersonalityScreen';
import { VoiceScreen } from './screens/VoiceScreen';
import { DatasetScreen } from './screens/DatasetScreen';
import styles from './App.module.css';

export type Screen = 'chat' | 'personality' | 'voice' | 'dataset';

const screenVariants = {
  initial: { opacity: 0, y: 16 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -16 },
};

export default function App() {
  const [activeScreen, setActiveScreen] = useState<Screen>('chat');
  const chat = useChat();

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
