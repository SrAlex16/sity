/**
 * R6-02 — handleSend() con canCancel=true silenciaba el Enter/tap.
 * Fix: mostrar busyHint breve y conservar el draft.
 */
import { render, screen, fireEvent, act } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('framer-motion', () => ({
  motion: {
    div: ({ children, style, className, onClick, ...rest }: React.HTMLAttributes<HTMLDivElement>) =>
      <div style={style} className={className} onClick={onClick} {...rest}>{children}</div>,
    button: ({ children, style, className, onClick, disabled, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement>) =>
      <button style={style} className={className} onClick={onClick} disabled={disabled} {...rest}>{children}</button>,
    span: ({ children, style, className }: React.HTMLAttributes<HTMLSpanElement>) =>
      <span style={style} className={className}>{children}</span>,
  },
  AnimatePresence: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock('../hooks/useVoice', () => ({
  useVoice: () => ({ settings: null }),
}));

vi.mock('../hooks/useNotifications', () => ({
  useNotifications: () => [],
}));

vi.mock('../components/TypingIndicator', () => ({ TypingIndicator: () => null }));
vi.mock('../components/StatusBadge', () => ({ StatusBadge: () => null }));
vi.mock('../components/BgJobIndicator', () => ({ BgJobIndicator: () => null }));
vi.mock('../components/BackgroundPicker', () => ({ BackgroundPicker: () => null }));
vi.mock('../components/FontPicker', () => ({ FontPicker: () => null }));
vi.mock('../components/MessageList', () => ({ MessageList: () => null }));
vi.mock('../components/RecordingUI', () => ({ RecordingUI: () => null }));
vi.mock('../utils/imageResize', () => ({
  resizeImageToBase64: vi.fn().mockResolvedValue({ base64: '', mediaType: 'image/jpeg' }),
}));
vi.mock('./ChatScreen.module.css', () => ({ default: new Proxy({}, { get: (_t, p) => String(p) }) }));

import { ChatScreen } from './ChatScreen';

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = vi.fn();

// ── Helpers ───────────────────────────────────────────────────────────────────

function makeProps(overrides: Partial<Parameters<typeof ChatScreen>[0]> = {}) {
  return {
    messages: [],
    status: 'desconectado' as const,
    sendMessage: vi.fn().mockResolvedValue(undefined),
    sendAudio: vi.fn().mockResolvedValue(undefined),
    clearMessages: vi.fn(),
    canCancel: false,
    cancel: vi.fn(),
    backgroundJobsActive: 0,
    backgroundJustFinished: false,
    quotaExhausted: false,
    uiLang: 'es' as const,
    ...overrides,
  };
}

// ── Tests ─────────────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  // handleKeyDown guards on maxTouchPoints===0 to skip mobile soft-keyboard Enter presses
  Object.defineProperty(navigator, 'maxTouchPoints', { value: 0, configurable: true, writable: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe('ChatScreen — R6-02 handleSend busyHint', () => {

  it('canCancel=true: muestra busyHint, NO llama sendMessage, conserva draft', async () => {
    const sendMessage = vi.fn();
    render(<ChatScreen {...makeProps({ canCancel: true, sendMessage })} />);

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'hola mundo' } });

    // simulate Enter (or send button click) while turn is active
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    // busyHint debe aparecer
    expect(screen.getByText('Espera a que termine la respuesta.')).toBeInTheDocument();

    // sendMessage no debe haberse llamado
    expect(sendMessage).not.toHaveBeenCalled();

    // draft intacto
    expect(textarea.value).toBe('hola mundo');

    // avanzar 2 s → hint desaparece
    await act(async () => { vi.advanceTimersByTime(2100); });
    expect(screen.queryByText('Espera a que termine la respuesta.')).not.toBeInTheDocument();
  });

  it('canCancel=false: llama sendMessage y limpia el input', async () => {
    const sendMessage = vi.fn().mockResolvedValue(undefined);

    render(<ChatScreen {...makeProps({ canCancel: false, sendMessage })} />);

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: 'mensaje válido' } });
    fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: false });

    expect(sendMessage).toHaveBeenCalledWith('mensaje válido', undefined);
    expect(textarea.value).toBe('');
  });

});
