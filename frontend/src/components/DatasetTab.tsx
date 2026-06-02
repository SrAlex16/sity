import { useState, useEffect } from "react";
import {
  type DatasetCaptureContext,
  type DatasetCaptureRequest,
  type DatasetStatsResponse,
} from "../api/debugApi";

// ---------------------------------------------------------------------------
// Shared primitives
// ---------------------------------------------------------------------------

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-950 px-4 py-3 text-center">
      <p className="text-2xl font-bold text-cyan-200">{value}</p>
      <p className="mt-1 text-xs text-zinc-500">{label}</p>
    </div>
  );
}

function ProgressBar({ progress }: { progress: number }) {
  const pct = Math.round(progress * 100);
  return (
    <div className="h-2 w-full rounded-full bg-zinc-800">
      <div
        className="h-2 rounded-full bg-cyan-500 transition-all"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dataset Capture
// ---------------------------------------------------------------------------

const PRESETS: Record<string, Partial<DatasetCaptureRequest>> = {
  normal_use: {
    dataset_source: "normal_use",
    speaker_source: "human_local",
    dataset_eligible: true,
    dataset_tags: [],
  },
  synthetic_claude_user: {
    dataset_source: "synthetic_claude_user",
    speaker_source: "synthetic_claude_user",
    dataset_eligible: true,
    dataset_tags: ["multi_persona"],
  },
  human_guest: {
    dataset_source: "human_guest",
    speaker_source: "human_guest",
    dataset_eligible: true,
    dataset_tags: [],
  },
  debug_test: {
    dataset_source: "debug_test",
    speaker_source: "human_local",
    dataset_eligible: false,
    dataset_tags: [],
  },
};

type CaptureForm = {
  enabled: boolean;
  dataset_source: string;
  speaker_label: string;
  speaker_source: string;
  speaker_confidence: string;
  dataset_eligible: boolean;
  dataset_tags: string;
};

function ctxToForm(ctx: DatasetCaptureContext | null): CaptureForm {
  return {
    enabled: ctx?.enabled ?? false,
    dataset_source: ctx?.dataset_source ?? "normal_use",
    speaker_label: ctx?.speaker_label ?? "",
    speaker_source: ctx?.speaker_source ?? "",
    speaker_confidence: ctx?.speaker_confidence != null ? String(ctx.speaker_confidence) : "",
    dataset_eligible: ctx?.dataset_eligible ?? true,
    dataset_tags: ctx?.dataset_tags?.join(", ") ?? "",
  };
}

function formToRequest(form: CaptureForm): DatasetCaptureRequest {
  const confidence = form.speaker_confidence.trim()
    ? parseFloat(form.speaker_confidence)
    : null;
  const tags = form.dataset_tags
    .split(",")
    .map((t) => t.trim())
    .filter(Boolean);
  return {
    enabled: form.enabled,
    dataset_source: form.dataset_source || "normal_use",
    speaker_label: form.speaker_label.trim() || null,
    speaker_source: form.speaker_source.trim() || null,
    speaker_confidence: confidence,
    dataset_eligible: form.dataset_eligible,
    dataset_tags: tags,
  };
}

function DatasetCaptureSection({
  capture,
  loading,
  error,
  onSave,
  onDisable,
}: {
  capture: DatasetCaptureContext | null;
  loading: boolean;
  error: string | null;
  onSave: (payload: DatasetCaptureRequest) => Promise<void>;
  onDisable: () => Promise<void>;
}) {
  const [form, setForm] = useState<CaptureForm>(() => ctxToForm(capture));
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    setForm(ctxToForm(capture));
  }, [capture]);

  function applyPreset(key: string) {
    const preset = PRESETS[key];
    if (!preset) return;
    setForm((prev) => ({
      ...prev,
      dataset_source: preset.dataset_source ?? prev.dataset_source,
      speaker_source: preset.speaker_source ?? prev.speaker_source,
      dataset_eligible: preset.dataset_eligible ?? prev.dataset_eligible,
      dataset_tags: preset.dataset_tags?.join(", ") ?? prev.dataset_tags,
    }));
  }

  async function handleSave() {
    setFormError(null);
    if (form.enabled && !form.speaker_source.trim()) {
      setFormError("speaker_source es obligatorio cuando capture está activo.");
      return;
    }
    const conf = form.speaker_confidence.trim();
    if (conf) {
      const n = parseFloat(conf);
      if (isNaN(n) || n < 0 || n > 1) {
        setFormError("speaker_confidence debe estar entre 0 y 1.");
        return;
      }
    }
    await onSave(formToRequest(form));
  }

  const isActive = capture?.enabled ?? false;

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold">Dataset Capture</h2>
          {isActive ? (
            <p className="mt-1 text-xs text-amber-300">
              Activo: {capture?.dataset_source}
              {capture?.speaker_label ? ` / ${capture.speaker_label}` : ""}
            </p>
          ) : (
            <p className="mt-1 text-xs text-zinc-500">Desactivado</p>
          )}
        </div>
        {isActive && (
          <button
            onClick={onDisable}
            disabled={loading}
            className="rounded-xl border border-red-800 px-4 py-2 text-sm text-red-300 hover:bg-red-950/50 disabled:opacity-50"
          >
            Desactivar
          </button>
        )}
      </div>

      {(error || formError) && (
        <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          {error ?? formError}
        </p>
      )}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <label className="flex items-center gap-3 sm:col-span-2">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm((p) => ({ ...p, enabled: e.target.checked }))}
            className="h-4 w-4 accent-cyan-400"
          />
          <span className="text-sm text-zinc-200">Capture activo</span>
        </label>

        <div className="sm:col-span-2">
          <p className="mb-1 text-xs text-zinc-500">Preset</p>
          <div className="flex flex-wrap gap-2">
            {Object.keys(PRESETS).map((key) => (
              <button
                key={key}
                onClick={() => applyPreset(key)}
                className="rounded-lg border border-zinc-700 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
              >
                {key}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-xs text-zinc-500">dataset_source</label>
          <input
            type="text"
            value={form.dataset_source}
            onChange={(e) => setForm((p) => ({ ...p, dataset_source: e.target.value }))}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>

        <div>
          <label className="block text-xs text-zinc-500">speaker_source</label>
          <input
            type="text"
            value={form.speaker_source}
            onChange={(e) => setForm((p) => ({ ...p, speaker_source: e.target.value }))}
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>

        <div>
          <label className="block text-xs text-zinc-500">speaker_label</label>
          <input
            type="text"
            value={form.speaker_label}
            onChange={(e) => setForm((p) => ({ ...p, speaker_label: e.target.value }))}
            placeholder="guest_confused_01"
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>

        <div>
          <label className="block text-xs text-zinc-500">speaker_confidence (0–1)</label>
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            value={form.speaker_confidence}
            onChange={(e) => setForm((p) => ({ ...p, speaker_confidence: e.target.value }))}
            placeholder="0.9"
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>

        <div>
          <label className="block text-xs text-zinc-500">dataset_tags (coma-separados)</label>
          <input
            type="text"
            value={form.dataset_tags}
            onChange={(e) => setForm((p) => ({ ...p, dataset_tags: e.target.value }))}
            placeholder="multi_persona, casual"
            className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-200 placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-cyan-500"
          />
        </div>

        <label className="flex items-center gap-3 self-end pb-2">
          <input
            type="checkbox"
            checked={form.dataset_eligible}
            onChange={(e) => setForm((p) => ({ ...p, dataset_eligible: e.target.checked }))}
            className="h-4 w-4 accent-cyan-400"
          />
          <span className="text-sm text-zinc-200">dataset_eligible</span>
        </label>
      </div>

      <div className="mt-5 flex gap-3">
        <button
          onClick={handleSave}
          disabled={loading}
          className="rounded-xl bg-cyan-600 px-5 py-2 text-sm font-medium text-white hover:bg-cyan-500 disabled:opacity-50"
        >
          {loading ? "Guardando…" : "Guardar"}
        </button>
        {isActive && (
          <button
            onClick={onDisable}
            disabled={loading}
            className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-800 disabled:opacity-50"
          >
            Desactivar
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Dataset Stats
// ---------------------------------------------------------------------------

function DatasetStatsSection({
  stats,
  loading,
  error,
}: {
  stats: DatasetStatsResponse | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !stats) {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-xl font-semibold">Dataset LoRA v1</h2>
        <p className="mt-3 text-sm text-zinc-500">Cargando estadísticas…</p>
      </div>
    );
  }

  if (error && !stats) {
    return (
      <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
        <h2 className="text-xl font-semibold">Dataset LoRA v1</h2>
        <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-red-200">
          {error}
        </p>
      </div>
    );
  }

  if (!stats) return null;

  const sortedTargets = Object.entries(stats.targets).sort(
    ([, a], [, b]) => b.target - b.count - (a.target - a.count),
  );
  const tagEntries = Object.entries(stats.by_tag).sort(([, a], [, b]) => b - a);
  const sourceEntries = Object.entries(stats.by_source).sort(([, a], [, b]) => b - a);

  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
      <div>
        <h2 className="text-xl font-semibold">Dataset LoRA v1</h2>
        <p className="mt-1 text-xs text-zinc-500">
          calculado {new Date(stats.computed_at).toLocaleString()}
          {loading && " · actualizando…"}
        </p>
      </div>

      {error && (
        <p className="mt-3 rounded-xl border border-red-900 bg-red-950/50 p-3 text-sm text-red-200">
          {error}
        </p>
      )}

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <StatCard label="Pares totales" value={stats.total_pairs} />
        <StatCard label="Utilizables" value={stats.usable_pairs} />
        <StatCard label="Sin tone_meta" value={stats.missing_tone_meta} />
        <StatCard label="Operacionales" value={stats.operational_pairs} />
        <StatCard label="Inelegibles" value={stats.ineligible_pairs} />
      </div>

      <div className="mt-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Targets por bucket
        </h3>
        <div className="mt-3 grid gap-3">
          {sortedTargets.map(([bucket, data]) => (
            <div key={bucket}>
              <div className="flex items-center justify-between text-sm">
                <span className="font-mono text-zinc-200">{bucket}</span>
                <span className="text-zinc-400">
                  {data.count} / {data.target}{" "}
                  <span className="text-zinc-500">({Math.round(data.progress * 100)}%)</span>
                </span>
              </div>
              <div className="mt-1">
                <ProgressBar progress={data.progress} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {sourceEntries.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Por fuente
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {sourceEntries.map(([src, count]) => (
              <span
                key={src}
                className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
              >
                {src}: <span className="font-semibold text-cyan-200">{count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="mt-6">
        <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
          Tags detectados
        </h3>
        {tagEntries.length === 0 ? (
          <p className="mt-2 text-sm text-zinc-500">Sin tags detectados todavía.</p>
        ) : (
          <div className="mt-2 flex flex-wrap gap-2">
            {tagEntries.map(([tag, count]) => (
              <span
                key={tag}
                className="rounded-full border border-zinc-700 px-3 py-1 text-xs text-zinc-300"
              >
                {tag}: <span className="font-semibold text-cyan-200">{count}</span>
              </span>
            ))}
          </div>
        )}
      </div>

      {stats.recent_pairs.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-zinc-400">
            Últimos pares utilizables
          </h3>
          <div className="mt-3 grid gap-2">
            {stats.recent_pairs.map((pair, i) => (
              <div
                key={i}
                className="rounded-xl border border-zinc-800 bg-zinc-950 p-3 text-xs"
              >
                <div className="flex flex-wrap gap-2 text-zinc-500">
                  <span>{new Date(pair.created_at).toLocaleString()}</span>
                  <span className="font-mono text-cyan-400">{pair.primary_bucket}</span>
                  <span>{pair.dataset_source}</span>
                  {pair.tags.map((t) => (
                    <span key={t} className="rounded border border-zinc-700 px-1 text-zinc-400">
                      {t}
                    </span>
                  ))}
                </div>
                <p className="mt-2 text-zinc-400">
                  <span className="text-zinc-500">U: </span>{pair.user_text}
                </p>
                <p className="mt-1 text-zinc-300">
                  <span className="text-zinc-500">S: </span>{pair.sity_text}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// DatasetTab (public export)
// ---------------------------------------------------------------------------

export type DatasetTabProps = {
  datasetStats: DatasetStatsResponse | null;
  datasetStatsLoading: boolean;
  datasetStatsError: string | null;
  datasetCapture: DatasetCaptureContext | null;
  datasetCaptureLoading: boolean;
  datasetCaptureError: string | null;
  onSaveDatasetCapture: (payload: DatasetCaptureRequest) => Promise<void>;
  onDisableDatasetCapture: () => Promise<void>;
  onRefresh: () => void;
};

export function DatasetTab({
  datasetStats,
  datasetStatsLoading,
  datasetStatsError,
  datasetCapture,
  datasetCaptureLoading,
  datasetCaptureError,
  onSaveDatasetCapture,
  onDisableDatasetCapture,
  onRefresh,
}: DatasetTabProps) {
  return (
    <div className="grid gap-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-zinc-300">Dataset LoRA v1</h2>
        <button
          onClick={onRefresh}
          className="rounded-xl border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-800"
        >
          Refrescar
        </button>
      </div>

      <DatasetCaptureSection
        capture={datasetCapture}
        loading={datasetCaptureLoading}
        error={datasetCaptureError}
        onSave={onSaveDatasetCapture}
        onDisable={onDisableDatasetCapture}
      />

      <DatasetStatsSection
        stats={datasetStats}
        loading={datasetStatsLoading}
        error={datasetStatsError}
      />
    </div>
  );
}
