import type { PersonalitySettings } from "../api/sityApi";

// Moved from App.tsx — only used by SettingsTab.
const LABELS: Record<keyof PersonalitySettings, string> = {
  sarcasm_level: "Sarcasmo",
  rudeness_level: "Mala leche",
  warmth_level: "Calidez",
  honesty_level: "Honestidad",
  initiative_level: "Iniciativa",
  dry_humor_level: "Humor seco",
  melancholy_level: "Melancolía",
  tsundere_level: "Modo tsundere",
  contrarian_level: "Contradicción",
  patience_level: "Paciencia",
  refusal_chance: "Probabilidad de negarse",
  helpfulness_level: "Nivel de ayuda",
  verbosity_level: "Verbosidad",
};

const ORDER: Array<keyof PersonalitySettings> = [
  "sarcasm_level",
  "rudeness_level",
  "warmth_level",
  "honesty_level",
  "initiative_level",
  "dry_humor_level",
  "melancholy_level",
  "tsundere_level",
  "contrarian_level",
  "patience_level",
  "refusal_chance",
  "helpfulness_level",
  "verbosity_level",
];

function percent(value: number): number {
  return Math.round(value * 100);
}

export type SettingsTabProps = {
  personality: PersonalitySettings | null;
  averageEdge: number;
  message: string;
  error: string | null;
  loading: boolean;
  savingKey: keyof PersonalitySettings | null;
  onReload: () => void;
  /** Optimistic update while the slider is being dragged. */
  onSliderChange: (key: keyof PersonalitySettings, value: number) => void;
  /** Committed value on mouseUp / touchEnd — triggers the API call. */
  onSliderCommit: (key: keyof PersonalitySettings, value: number) => void;
};

export function SettingsTab({
  personality,
  averageEdge,
  message,
  error,
  loading,
  savingKey,
  onReload,
  onSliderChange,
  onSliderCommit,
}: SettingsTabProps) {
  return (
    <>
      <section className="grid gap-4 md:grid-cols-[1fr_280px]">
        <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-xl font-semibold">Respuesta de Sity</h2>
          <p className="mt-3 rounded-xl bg-zinc-950 p-4 text-cyan-100">
            {message}
          </p>
          {error && (
            <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
              {error}
            </p>
          )}
        </div>

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <h2 className="text-xl font-semibold">Encabronamiento</h2>
          <p className="mt-4 text-5xl font-bold text-cyan-300">{averageEdge}%</p>
          <p className="mt-2 text-sm text-zinc-400">
            Media de sarcasmo, mala leche, humor seco, tsundere y contradicción. Métrica científicamente dudosa, como casi todo lo divertido.
          </p>
        </div>
      </section>

      <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-xl font-semibold">Parámetros</h2>
          <button
            onClick={onReload}
            className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
          >
            Recargar
          </button>
        </div>

        {loading && <p className="mt-4 text-zinc-400">Cargando...</p>}

        {personality && (
          <div className="mt-6 grid gap-5">
            {ORDER.map((key) => (
              <div key={key} className="rounded-xl bg-zinc-950 p-4">
                <div className="mb-3 flex items-center justify-between gap-4">
                  <div>
                    <p className="font-medium">{LABELS[key]}</p>
                    <p className="text-sm text-zinc-500">{key}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold text-cyan-300">
                      {percent(personality[key])}%
                    </p>
                    {savingKey === key && (
                      <p className="text-xs text-zinc-500">guardando...</p>
                    )}
                  </div>
                </div>

                <input
                  type="range"
                  min="0"
                  max="100"
                  value={percent(personality[key])}
                  onChange={(event) => {
                    onSliderChange(key, Number(event.target.value) / 100);
                  }}
                  onMouseUp={(event) => {
                    onSliderCommit(
                      key,
                      Number((event.target as HTMLInputElement).value) / 100,
                    );
                  }}
                  onTouchEnd={(event) => {
                    onSliderCommit(
                      key,
                      Number((event.target as HTMLInputElement).value) / 100,
                    );
                  }}
                  className="w-full"
                />
              </div>
            ))}
          </div>
        )}
      </section>
    </>
  );
}
