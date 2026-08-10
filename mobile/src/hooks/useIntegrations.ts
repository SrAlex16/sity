import { useState, useEffect, useCallback } from 'react';

export interface IntegrationStatus {
  provider: string;
  connected: boolean;
  scopes: string | null;
  connected_at: string | null;
}

export function useIntegrations() {
  const [integrations, setIntegrations] = useState<IntegrationStatus[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const resp = await fetch('/auth/integrations', { credentials: 'include' });
      if (!resp.ok) {
        setError('No se pudo cargar el estado de las integraciones');
        return;
      }
      setIntegrations(await resp.json() as IntegrationStatus[]);
    } catch {
      setError('Error de red');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  return { integrations, isLoading, error, refresh: load };
}
