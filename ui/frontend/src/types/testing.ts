// Types for the admin Search & AI-Summary evaluation harness (superuser-only).

export type TestCapability = 'search' | 'ai_summary';
export type ExperimentStatus = 'draft' | 'pending' | 'running' | 'completed' | 'failed';
export type ResultStatus = 'pass' | 'fail' | 'error';

// Per-case enable flag + which assertion columns apply (aligned to columns).
// `ovr` (aligned to columns) holds an optional per-cell rubric override used for
// llm_judge columns: a non-empty value runs that prompt for the row instead of
// the column's default rubric.
export interface CaseRowState {
  active: boolean;
  cols: boolean[];
  ovr?: string[];
}

// Assertions live on the experiment as a cases x assertions matrix: a set of
// assertion columns plus, per test case, an active flag and per-column toggles.
export interface AssertionMatrix {
  columns: Assertion[];
  cases: Record<string, CaseRowState>;
}

export interface TestDataset {
  id: string;
  name: string;
  description?: string | null;
  capability: TestCapability;
  data_source: string;
  created_by_user_id?: string | null;
  created_at: string;
  updated_at: string;
  num_cases?: number | null;
  last_run_at?: string | null;
  last_pass_rate?: number | null;
}

// A single assertion specification. `type` is required; the remaining keys are
// assertion-specific parameters (id, k, value, text, pattern, rubric, ...).
export interface Assertion {
  type: string;
  [key: string]: unknown;
}

// A dataset row — inputs only (assertions live on the experiment).
export interface TestCase {
  id: string;
  dataset_id: string;
  input: Record<string, unknown>;
  tags?: string[] | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssertionResult {
  type: string;
  passed: boolean;
  message: string;
  score?: number;
  // For llm_judge: the rubric and the exact prompt sent to the judge LLM.
  rubric?: string;
  judge_prompt?: string;
}

// Emitted only while a run is in flight, so the UI can show how far it has
// progressed. Replaced by the aggregate fields below once the run completes.
export interface RunProgress {
  completed: number;
  total: number;
}

export interface SummaryStats {
  total: number;
  passed: number;
  failed: number;
  errored: number;
  pass_rate: number;
  mean_score?: number | null;
  duration_ms: number;
  // Total LLM usage across the run's cases (summary + judge calls).
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number | null;
  error?: string;
  progress?: RunProgress | null;
}

export interface TestExperiment {
  id: string;
  dataset_id: string;
  name: string;
  status: ExperimentStatus;
  config?: Record<string, unknown> | null;
  case_expectations?: AssertionMatrix | null;
  summary_stats?: SummaryStats | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_by_user_id?: string | null;
  created_at: string;
}

export interface TestResult {
  id: string;
  experiment_id: string;
  run_id?: string | null;
  test_case_id: string;
  status: ResultStatus;
  score?: number | null;
  actual_output?: Record<string, unknown> | null;
  assertion_results?: AssertionResult[] | null;
  latency_ms?: number | null;
  error_message?: string | null;
  created_at: string;
}

// One execution of an experiment, with its own stats and per-case results.
export interface TestRun {
  id: string;
  experiment_id: string;
  run_number: number;
  status: ExperimentStatus;
  summary_stats?: SummaryStats | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  results: TestResult[];
}

export interface ExperimentDetail extends TestExperiment {
  runs: TestRun[];
}

// ---------------------------------------------------------------------------
// Brief citation check (Evaluation Harness "Brief" type)
// ---------------------------------------------------------------------------

export type CitationVerdict = 'supported' | 'partially_supported' | 'unsupported' | 'cannot_assess';
export type CheckStatus = 'pending' | 'running' | 'completed' | 'failed';

export interface CheckSectionStats {
  brief_section: string;
  supported: number;
  partially_supported: number;
  unsupported: number;
  cannot_assess: number;
  total: number;
  flagged_share: number;
}

export interface CheckSummaryStats {
  total?: number;
  verdicts?: Record<CitationVerdict, number>;
  flagged?: number;
  flagged_share?: number;
  quote_not_in_source?: number;
  not_judged?: number;
  by_section?: CheckSectionStats[];
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cost_usd?: number | null;
  error?: string;
  progress?: RunProgress | null;
}

export interface BriefCitationCheck {
  id: string;
  brief_id: string;
  brief_title: string;
  data_source?: string | null;
  created_by_user_id?: string | null;
  judge_model?: string | null;
  model_combo?: string | null;
  status: CheckStatus;
  summary_stats?: CheckSummaryStats | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}

// A brief the current user may check (own, or shared with them).
export interface BriefCheckCandidate {
  id: string;
  title: string;
  data_source?: string | null;
  updated_at: string;
  owner_name: string;
  shared: boolean;
  researched_sections: number;
  cited_passages: number;
  last_check?: BriefCitationCheck | null;
}

export interface CheckSource {
  index: number;
  title?: string | null;
  page?: number | null;
  doc_id?: string | null;
  chunk_id?: string | null;
  pdf_url?: string | null;
  section?: string;
  excerpt?: string;
}

export interface CheckQuote {
  citation?: number | null;
  quote: string;
  status: 'verbatim' | 'near' | 'missing';
}

// One judged passage: a row of the review table.
export interface BriefCitationCheckPassage {
  id: string;
  passage_id: number;
  brief_section: string;
  passage: string;
  citations: string;
  documents: string;
  sources: CheckSource[];
  dangling_citations: string;
  verdict: CitationVerdict;
  flagged: boolean;
  confidence?: number | null;
  problems: string[];
  explanation: string;
  supporting_quotes: CheckQuote[];
  quotes_verified: string;
  quote_not_in_source: boolean;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  error_message?: string | null;
}

export interface BriefCitationCheckDetail extends BriefCitationCheck {
  passages: BriefCitationCheckPassage[];
}
