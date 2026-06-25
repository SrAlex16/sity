import { useState } from 'react';

export type DatasetPreset = 'normal_use' | 'demo_session' | 'debug_test';

export interface DatasetStatus {
  dataset_source: DatasetPreset;
}

export function useDataset() {
  const [status, _setStatus] = useState<DatasetStatus | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const fetchStatus = async (): Promise<void> => {
    setIsLoading(true);
    try {
      // TODO: GET /debug/dataset-capture
    } finally {
      setIsLoading(false);
    }
  };

  const setPreset = async (_preset: DatasetPreset): Promise<void> => {
    // TODO: PUT /debug/dataset-capture
    void fetchStatus();
  };

  return { status, isLoading, fetchStatus, setPreset };
}
