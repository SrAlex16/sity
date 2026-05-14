import { useEffect, useMemo, useState } from "react";
import {
  adjustPersonality,
  getPersonality,
  type PersonalitySettings,
} from "./api/sityApi";
import "./App.css";

const LABELS: Record<keyof PersonalitySettings, string> = {
  sarcasm_level: "Sarcasmo",
  rudeness_level: "Mala leche",
  warmth_level: "Calidez",
  honesty_level: "Honestidad",
  autonomy_level: "Autonomía",
  proactivity_level: "Proactividad",
  glados_mode: "Modo GLaDOS",
  tsundere_level: "Modo tsundere",
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
  "autonomy_level",
  "proactivity_level",
  "glados_mode",
  "tsundere_level",
  "patience_level",
  "refusal_chance",
  "helpfulness_level",
  "verbosity_level",
];

function percent(value: number): number {
  return Math.round(value * 100);
}

function App() {
  const [personality, setPersonality] = useState<PersonalitySettings | null>(null);
  const [message, setMessage] = useState<string>("Sity inicializando personalidad...");
  const [loading, setLoading] = useState<boolean>(true);
  const [savingKey, setSavingKey] = useState<keyof PersonalitySettings | null>(null);
  const [error, setError] = useState<string | null>(null);

  const averageEdge = useMemo(() => {
    if (!personality) return 0;
    return Math.round(
      ((personality.sarcasm_level +
        personality.rudeness_level +
        personality.glados_mode +
        personality.tsundere_level) /
        4) *
        100,
    );
  }, [personality]);

  async function refresh() {
    setLoading(true);
    setError(null);

    try {
      const data = await getPersonality();
      setPersonality(data);
      setMessage("Personalidad cargada. Por desgracia para ti, sigo funcionando.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setMessage("No he podido cargar mi personalidad. Qué forma tan elegante de empezar.");
    } finally {
      setLoading(false);
    }
  }

  async function setAbsolute(parameter: keyof PersonalitySettings, value: number) {
    setSavingKey(parameter);
    setError(null);

    try {
      const response = await adjustPersonality(parameter, "set_absolute", value);
      setPersonality((current) =>
        current
          ? {
              ...current,
              [parameter]: response.new_value,
            }
          : current,
      );
      setMessage(response.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error desconocido");
      setMessage("No he podido guardar el ajuste. Fascinante incompetencia técnica.");
    } finally {
      setSavingKey(null);
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <main className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <header className="rounded-2xl border border-zinc-800 bg-zinc-900/80 p-6 shadow-xl">
          <p className="text-sm uppercase tracking-[0.35em] text-cyan-300">
            Sity Core
          </p>
          <h1 className="mt-3 text-4xl font-bold">Personality Calibration</h1>
          <p className="mt-3 max-w-3xl text-zinc-300">
            Ajusta los parámetros tipo TARS. Yo protestaré si hace falta, pero el sistema aplicará los cambios. Qué tragedia para mi dignidad.
          </p>
        </header>

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
              Media de sarcasmo, mala leche, GLaDOS y tsundere. Métrica científicamente dudosa, como casi todo lo divertido.
            </p>
          </div>
        </section>

        <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
          <div className="flex items-center justify-between gap-4">
            <h2 className="text-xl font-semibold">Parámetros</h2>
            <button
              onClick={refresh}
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
                      const value = Number(event.target.value) / 100;
                      setPersonality((current) =>
                        current
                          ? {
                              ...current,
                              [key]: value,
                            }
                          : current,
                      );
                    }}
                    onMouseUp={(event) => {
                      const value = Number(
                        (event.target as HTMLInputElement).value,
                      ) / 100;
                      setAbsolute(key, value);
                    }}
                    onTouchEnd={(event) => {
                      const value = Number(
                        (event.target as HTMLInputElement).value,
                      ) / 100;
                      setAbsolute(key, value);
                    }}
                    className="w-full"
                  />
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

export default App;
