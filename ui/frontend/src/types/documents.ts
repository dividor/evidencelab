export interface StatsData {
  total_documents: number;
  indexed_documents: number;
  total_agencies: number;
  status_breakdown: Record<string, number>;
  agency_breakdown: Record<string, number | Record<string, number>>;
  agency_indexed: Record<string, number>;
  type_breakdown: Record<string, number | Record<string, number>>;
  type_indexed: Record<string, number>;
  year_breakdown: Record<string, number | Record<string, number>>;
  year_indexed?: Record<string, number>;
  language_breakdown?: Record<string, number | Record<string, number>>;
  language_indexed?: Record<string, number>;
  format_breakdown?: Record<string, number | Record<string, number>>;
  format_indexed?: Record<string, number>;
  country_breakdown?: Record<string, number | Record<string, number>>;
  country_indexed?: Record<string, number>;
}
