import { useState } from 'react';

export interface PersonalitySettings {
  sarcasm_level: number;
  rudeness_level: number;
  warmth_level: number;
  honesty_level: number;
  initiative_level: number;
  dry_humor_level: number;
  frialdad_afectiva_level: number;
  contrarian_level: number;
  patience_level: number;
  refusal_chance: number;
  helpfulness_level: number;
  verbosity_level: number;
  melancholy_level: number;
  skepticism_level: number;
}

export function usePersonality() {
  const [settings, setSettings] = useState<PersonalitySettings | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const updateSetting = async (_key: keyof PersonalitySettings, _value: number): Promise<void> => {
    // TODO: implement
  };

  const resetPersonality = async (): Promise<void> => {
    setIsLoading(true);
    try {
      // TODO: implement
    } finally {
      setIsLoading(false);
    }
  };

  return { settings, isLoading, updateSetting, resetPersonality };
}
