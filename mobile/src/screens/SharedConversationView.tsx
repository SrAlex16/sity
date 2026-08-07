/**
 * Read-only view for shared conversations accessed via /shared/{id}.
 * No chat input, no session, no tools — just the snapshot.
 */
import { useEffect, useState } from 'react';
import styles from './SharedConversationView.module.css';

interface SharedMessage {
  role: string;
  text: string;
  created_at: string;
}

interface SharedData {
  share_id: string;
  messages: SharedMessage[];
  created_at: string;
  expires_at: string;
  view_count: number;
}

interface Props {
  shareId: string;
}

export function SharedConversationView({ shareId }: Props) {
  const [data, setData] = useState<SharedData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`/chat/shared/${shareId}`)
      .then(async (res) => {
        if (res.status === 410) {
          setError('Este enlace ha caducado o ya no existe.');
        } else if (res.status === 404) {
          setError('No se pudo cargar la conversación (error de conexión). Inténtalo de nuevo más tarde.');
        } else if (!res.ok) {
          setError(`No se pudo cargar la conversación (error ${res.status}). Inténtalo de nuevo más tarde.`);
        } else {
          setData(await res.json() as SharedData);
        }
      })
      .catch(() => setError('No se pudo cargar la conversación. Comprueba tu conexión e inténtalo de nuevo.'));
  }, [shareId]);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <span className={styles.brand}>Sity</span>
        <span className={styles.badge}>Conversación compartida · solo lectura</span>
      </header>

      <div className={styles.content}>
        {error && (
          <div className={styles.error}>{error}</div>
        )}

        {!error && !data && (
          <div className={styles.loading}>Cargando…</div>
        )}

        {data && (
          <>
            <div className={styles.meta}>
              Compartida el {new Date(data.created_at).toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' })}
              {' · '}Caduca el {new Date(data.expires_at).toLocaleDateString('es-ES', { day: 'numeric', month: 'long', year: 'numeric' })}
            </div>

            {data.messages.length === 0 && (
              <div className={styles.empty}>Esta conversación no tiene mensajes.</div>
            )}

            <div className={styles.messages}>
              {data.messages.map((msg, i) => (
                <div
                  key={i}
                  className={`${styles.bubble} ${msg.role === 'user' ? styles.bubbleUser : styles.bubbleSity}`}
                >
                  <span className={styles.roleLabel}>{msg.role === 'user' ? 'Tú' : 'Sity'}</span>
                  <p className={styles.text}>{msg.text}</p>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
