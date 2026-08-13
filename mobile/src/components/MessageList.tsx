import { AnimatePresence } from 'framer-motion';
import { memo } from 'react';
import type { ChatMessage } from '../hooks/useChat';
import { MessageBubble } from './MessageBubble';
import { AudioMessageBubble } from './AudioMessageBubble';
import type { UiLang } from '../i18n/translations';

interface MessageListProps {
  messages: ChatMessage[];
  activeAudioId: string | null;
  onAudioPlay: (id: string) => void;
  onAudioEnded: (id: string) => void;
  voiceIncludeText: boolean;
  uiLang?: UiLang;
}

function MessageListComponent({
  messages,
  activeAudioId,
  onAudioPlay,
  onAudioEnded,
  voiceIncludeText,
  uiLang = 'es',
}: MessageListProps) {
  return (
    <AnimatePresence initial={false}>
      {messages.map((msg, idx) => {
        if (msg.type === 'audio') {
          const next = messages[idx + 1];
          const nextAudioId = (
            next?.type === 'audio' &&
            next.trace_id &&
            next.trace_id === msg.trace_id
          ) ? next.id : undefined;
          return (
            <AudioMessageBubble
              key={msg.id}
              message={msg}
              showText={msg.role === 'user' || voiceIncludeText}
              isActive={activeAudioId === msg.id}
              onPlay={onAudioPlay}
              onEnded={onAudioEnded}
              nextAudioId={nextAudioId}
              uiLang={uiLang}
            />
          );
        }
        return <MessageBubble key={msg.id} message={msg} />;
      })}
    </AnimatePresence>
  );
}

export const MessageList = memo(MessageListComponent);
