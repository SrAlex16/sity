import { useState, useEffect } from 'react';

export type ChatStatus = 'conectado' | 'procesando' | 'desconectado';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: Date;
  isError?: boolean;
}

function uid(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
}

interface ApiMessage {
  role: string;
  text: string;
  created_at?: string;
}

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [status, setStatus] = useState<ChatStatus>('desconectado');

  useEffect(() => {
    void loadHistory();
  }, []);

  async function loadHistory() {
    try {
      const res = await fetch('/chat/current');
      if (!res.ok) throw new Error('network');
      const data = await res.json() as { messages: ApiMessage[] };
      setMessages(
        data.messages.map((m) => ({
          id: uid(),
          role: m.role === 'user' ? 'user' : 'assistant',
          text: m.text,
          timestamp: m.created_at ? new Date(m.created_at) : new Date(),
        })),
      );
      setStatus('conectado');
    } catch {
      setStatus('desconectado');
    }
  }

  async function sendMessage(text: string) {
    const userMsg: ChatMessage = { id: uid(), role: 'user', text, timestamp: new Date() };
    setMessages((prev) => [...prev, userMsg]);
    setStatus('procesando');

    try {
      const res = await fetch('/chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, source_channel: 'mobile' }),
      });
      if (!res.ok) throw new Error('network');
      const data = await res.json() as { text: string; ok: boolean };
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: 'assistant', text: data.text, timestamp: new Date() },
      ]);
      setStatus('conectado');
    } catch {
      setMessages((prev) => [
        ...prev,
        { id: uid(), role: 'assistant', text: 'Sin respuesta del servidor.', timestamp: new Date(), isError: true },
      ]);
      setStatus('desconectado');
    }
  }

  function clearMessages() {
    setMessages([]);
  }

  return { messages, status, sendMessage, clearMessages };
}
