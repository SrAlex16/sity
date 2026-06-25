import { useState } from 'react';

export interface ChatMessage {
  role: 'user' | 'assistant';
  text: string;
  timestamp: Date;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = async (_text: string): Promise<void> => {
    setIsLoading(true);
    try {
      // TODO: implement
    } finally {
      setIsLoading(false);
    }
  };

  return { messages, isLoading, sendMessage };
}
