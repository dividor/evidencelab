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
