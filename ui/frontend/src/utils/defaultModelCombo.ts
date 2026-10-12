import { ModelComboConfig } from '../types/api';

/**
 * The model combo a visitor starts on.
 *
 * `config.json` already marks it with `ui_model_combos.<name>.default: true`,
 * and the backend honours that flag in `get_default_model_combo()` — the
 * evaluation harness and the A2A server both use it. The UI did not: it
 * started on whichever combo came first in the file, so the two could
 * disagree the moment anyone reordered `ui_model_combos`.
 *
 * Behaviour matches the backend exactly: the flagged combo if there is one,
 * otherwise the first. A deployment that flags nothing is unaffected.
 */
export function resolveDefaultModelCombo(
  available: string[],
  combos: Record<string, ModelComboConfig> = {},
): string {
  // Walk the combos in config order, as the backend's
  // get_default_model_combo() does, so both pick the same one when several
  // are flagged. `available` is filtered by the API to combos whose embedding
  // model is indexed for the datasource, so a flagged combo can legitimately
  // be absent — that datasource simply does not support it.
  const flagged = Object.entries(combos)
    .find(([name, config]) => config?.default === true && available.includes(name));
  return (flagged && flagged[0]) || available[0] || '';
}
