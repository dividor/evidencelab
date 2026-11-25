export interface FootprintRanges {
  energy_kwh_min: number | null;
  energy_kwh_max: number | null;
  gwp_kgco2eq_min: number | null;
  gwp_kgco2eq_max: number | null;
  water_l_min: number | null;
  water_l_max: number | null;
}

export const FOOTPRINT_COLUMNS = [
  { measure: 'energy_kwh', label: 'Energy (Wh)' },
  { measure: 'gwp_kgco2eq', label: 'Emissions (g CO₂e)' },
  { measure: 'water_l', label: 'Water (mL)' },
] as const;

export type FootprintMeasure = (typeof FOOTPRINT_COLUMNS)[number]['measure'];

// The API stores kWh, kg CO₂e and litres. Display Wh, g and mL.
const formatEstimate = (value: number): string =>
  (value * 1000).toLocaleString(undefined, { maximumSignificantDigits: 2 });

export const formatFootprintRange = (
  fields: FootprintRanges,
  measure: FootprintMeasure,
): string | null => {
  const low = fields[`${measure}_min`];
  const high = fields[`${measure}_max`];
  if (low == null || high == null) return null;
  return `${formatEstimate(low)}–${formatEstimate(high)}`;
};
