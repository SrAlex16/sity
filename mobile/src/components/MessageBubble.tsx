import { motion } from 'framer-motion';
import type { ChatMessage } from '../hooks/useChat';
import styles from './MessageBubble.module.css';

function formatTimestamp(date: Date): string {
  const now = new Date();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);

  const time = date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
  if (date.toDateString() === now.toDateString()) return time;
  if (date.toDateString() === yesterday.toDateString()) return `Ayer ${time}`;

  const day = date.toLocaleDateString('es-ES', { day: '2-digit', month: 'short' }).replace('.', '');
  return `${day} ${time}`;
}

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';

  return (
    <motion.div
      className={`${styles.wrapper} ${isUser ? styles.wrapperUser : styles.wrapperSity}`}
      initial={{ opacity: 0, x: isUser ? 20 : -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.25, ease: 'easeOut' }}
      layout
    >
      <div
        className={`${styles.bubble} ${isUser ? styles.bubbleUser : styles.bubbleSity} ${message.isError ? styles.bubbleError : ''}`}
      >
        <p className={styles.text}>{message.text}</p>
      </div>
      <span className={styles.timestamp}>{formatTimestamp(message.timestamp)}</span>
    </motion.div>
  );
}
