import { useState, useEffect } from 'react';

export interface DatasetCaptureContext {
  ok: boolean;
  enabled: boolean;
  dataset_source: string;
  speaker_label: string | null;
  speaker_source: string | null;
  speaker_confidence: number | null;
  dataset_eligible: boolean;
  dataset_tags: string[];
  updated_at: string | null;
}

export interface DatasetCaptureRequest {
  enabled: boolean;
  dataset_source?: string;
  speaker_label?: string | null;
  speaker_source?: string | null;
  speaker_confidence?: number | null;
  dataset_eligible?: boolean;
  dataset_tags?: string[];
}

export function useDataset() {
  const [capture, setCapture] = useState<DatasetCaptureContext | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { void load(); }, []);

  async function load() {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/debug/dataset-capture');
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setCapture(await r.json() as DatasetCaptureContext);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al cargar');
    } finally {
      setIsLoading(false);
    }
  }

  async function save(payload: DatasetCaptureRequest) {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/debug/dataset-capture', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const detail = await r.text();
        throw new Error(`HTTP ${r.status}: ${detail}`);
      }
      setCapture(await r.json() as DatasetCaptureContext);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al guardar');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  async function disable() {
    setIsLoading(true);
    setError(null);
    try {
      const r = await fetch('/debug/dataset-capture/disable', { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setCapture(await r.json() as DatasetCaptureContext);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Error al desactivar');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  return { capture, isLoading, error, save, disable, reload: load };
}
