// Small, shared formatting helpers for the testing harness UI.

export const formatPercent = (rate?: number | null): string => {
  if (rate === null || rate === undefined) return '-';
  return `${Math.round(rate * 100)}%`;
};

export const formatScore = (score?: number | null): string => {
  if (score === null || score === undefined) return '-';
  return score.toFixed(2);
};

export const formatMs = (ms?: number | null): string => {
  if (ms === null || ms === undefined) return '-';
  return `${Math.round(ms)} ms`;
};

// An elapsed time as people say it: "4.2 s", "48 s", "2 min 14 s", "1 h 05 min".
export const formatElapsed = (ms?: number | null): string => {
  if (ms === null || ms === undefined || ms < 0) return '-';
  const seconds = ms / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)} s`;
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${Math.round(seconds - minutes * 60)} s`;
  const hours = Math.floor(minutes / 60);
  return `${hours} h ${String(minutes - hours * 60).padStart(2, '0')} min`;
};

export const formatTokens = (tokens?: number | null): string => {
  if (tokens === null || tokens === undefined) return '-';
  return tokens.toLocaleString();
};

export const formatCostUsd = (cost?: number | null): string => {
  if (cost === null || cost === undefined) return '-';
  return `$${cost.toFixed(4)}`;
};

export const formatTimestamp = (ts?: string | null): string => {
  if (!ts) return '-';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
};

// Pretty-print a JSON-like value without ever throwing on cyclic / odd input.
export const prettyJson = (value: unknown): string => {
  if (value === null || value === undefined) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};
