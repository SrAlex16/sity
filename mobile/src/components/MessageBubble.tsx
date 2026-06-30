import { useState } from 'react';
import { motion } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { TextChatMessage } from '../hooks/useChat';
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
  message: TextChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const [overlayOpen, setOverlayOpen] = useState(false);

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
        <div className={styles.text}>
          {message.imagePreviewUrl && (
            <>
              <img
                src={message.imagePreviewUrl}
                alt="imagen adjunta"
                className={styles.messageImage}
                onClick={() => setOverlayOpen(true)}
              />
              {overlayOpen && (
                <div
                  className={styles.imageOverlay}
                  onClick={() => setOverlayOpen(false)}
                >
                  <img
                    src={message.imagePreviewUrl}
                    alt="imagen ampliada"
                    className={styles.imageOverlayImg}
                  />
                </div>
              )}
            </>
          )}
          {message.text && (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: 'var(--neon-cyan)', textDecoration: 'underline' }}
                  >
                    {children}
                  </a>
                ),
                code: ({ children }) => (
                  <code style={{
                    background: 'rgba(0,0,0,0.4)',
                    padding: '2px 6px',
                    borderRadius: '4px',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.9em',
                  }}>
                    {children}
                  </code>
                ),
                pre: ({ children }) => (
                  <pre style={{
                    background: 'rgba(0,0,0,0.4)',
                    padding: '12px',
                    borderRadius: '8px',
                    overflowX: 'auto',
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.85em',
                    border: '1px solid var(--color-border)',
                  }}>
                    {children}
                  </pre>
                ),
                p: ({ children }) => (
                  <p style={{ margin: '0 0 8px 0' }}>{children}</p>
                ),
                ul: ({ children }) => (
                  <ul style={{ paddingLeft: '20px', margin: '4px 0' }}>{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol style={{ paddingLeft: '20px', margin: '4px 0' }}>{children}</ol>
                ),
              }}
            >
              {message.text}
            </ReactMarkdown>
          )}
          {message.isCancelled && (
            <span className={styles.msgCancelled}>[ respuesta interrumpida ]</span>
          )}
        </div>
      </div>
      <span className={styles.timestamp}>{formatTimestamp(message.timestamp)}</span>
    </motion.div>
  );
}
