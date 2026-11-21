/**
 * The message to show for a failed brief request: the API's own reason when
 * it gave one (FastAPI's `detail`, e.g. "This change is no longer awaiting
 * review"), not axios' "Request failed with status code 400"; otherwise the
 * error's message, or `fallback` for something that is not an Error.
 */
export const errorText = (e: unknown, fallback: string): string => {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === 'string' && detail) return detail;
  return e instanceof Error ? e.message : fallback;
};
