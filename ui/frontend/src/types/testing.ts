// Types for the admin Search & AI-Summary evaluation harness (superuser-only).

export type TestCapability = 'search' | 'ai_summary' | 'brief';
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

export interface RepeatedPassage {
  source_index: number;
  source_quote: string;
  target_quote: string;
  assessment?: string;
}

export interface AssertionResult {
  relevance?: { negatives: string[]; positives: string[] };
  repetitions?: RepeatedPassage[];
  section_assessment?: string;
  type: string;
  label?: string;
  quoted_claims?: number[];
  factual_support?: boolean;
  threshold?: number;
  claim_grades?: { claim: number; outcome?: string; verdict?: CitationVerdict; unmet?: string[];
    supporting_quotes?: { citation: number; quote: string }[]; reason: string; score?: number; passed?: boolean; error?: boolean }[];
  error?: boolean;
  not_run?: boolean;
  applicable?: boolean;
  passed?: boolean;
  message: string;
  score?: number;
  // For llm_judge: the rubric and the exact prompt sent to the judge LLM.
  rubric?: string;
  judge_prompt?: string;
}

// Emitted only while a run is in flight, so the UI can show how far it has
// progressed. Replaced by the aggregate fields below once the run completes.
export interface RunProgress {
  remaining_sections?: { template: string; heading: string; number?: string }[];
  completed: number;
  total: number;
}

export interface FactualClaimMetrics {
  factual_claim_mean_score?: number | null;
  factual_claim_pass_rate?: number | null;
}

export interface SummaryStats extends FactualClaimMetrics {
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

export interface BriefEvalClaim {
  parts: Array<{ text: string; marker?: boolean }>;
  references: number[];
}

export interface BriefEvalReference {
  label: string;
  source_position: number | null;
}

export interface BriefEvalEvidence {
  paragraphs: BriefEvalClaim[][];
  references: BriefEvalReference[];
}

export interface TestResult extends FactualClaimMetrics {
  id: string;
  experiment_id: string;
  run_id?: string | null;
  test_case_id: string | null;
  status: ResultStatus;
  score?: number | null;
  actual_output?: Record<string, unknown> | null;
  brief_evidence?: BriefEvalEvidence | null;
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
  /** Models, group and settings the run executed with (absent for older runs). */
  config?: Record<string, unknown> | null;
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

export interface CheckSummaryStats extends FactualClaimMetrics {
  pass_rate?: number;
  mean_score?: number | null;
  section_counts?: Record<ResultStatus, number>;
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
  check_kind?: "citation" | "full";
  id: string;
  brief_id: string;
  brief_title: string;
  data_source?: string | null;
  created_by_user_id?: string | null;
  judge_model?: string | null;
  model_combo?: string | null;
  // The brief version the check judged (null on checks made before versions
  // were linked) and whether the brief has a newer version since (null when
  // no version was recorded). Both decided by the API.
  brief_version_number?: number | null;
  brief_changed?: boolean | null;
  status: CheckStatus;
  summary_stats?: CheckSummaryStats | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}

// How the current user can see a brief: their own, shared with them, or (admins
// only) another user's brief that was not shared.
export type BriefAccess = 'own' | 'shared' | 'other';

// A brief the current user may check.
export interface BriefCheckCandidate {
  id: string;
  title: string;
  data_source?: string | null;
  updated_at: string;
  owner_name: string;
  access: BriefAccess;
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
  // Trace back to the agent's original output: the brief-wide source id,
  // the agent's own number(s) for it in the section, and the run.
  source_id?: string | null;
  agent_indices?: number[];
  run_id?: string | null;
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

export type BriefSectionReview = FactualClaimMetrics & Pick<TestResult, 'actual_output' | 'brief_evidence' | 'assertion_results' | 'status' | 'score' | 'latency_ms' | 'error_message'> & {
  section_id: string; heading: string; number: string;
};

export interface BriefCitationCheckDetail extends BriefCitationCheck {
  section_results?: BriefSectionReview[] | null;
  passages: BriefCitationCheckPassage[];
}

// One passage the Fact Checker highlights in an open brief: where it is,
// what the judge decided and why. `passage` is the prose as the check stored
// it (citation markers and markdown removed); the document locates it in the
// rendered section.
export interface BriefFactCheckMark {
  claim_text?: string | null;
  grade?: NonNullable<AssertionResult['claim_grades']>[number] | null;
  passage_id: number;
  section_id: string | null;
  section_title: string;
  passage: string;
  verdict: CitationVerdict;
  verdict_label: string;
  explanation: string;
  problems: string[];
  confidence?: number | null;
  citations: string;
  quote_not_in_source: boolean;
}

// A section with cited passages that changed since the check judged the
// brief: not covered, with the note the document shows above it.
export interface BriefFactCheckSection {
  id: string;
  title: string;
  note: string;
}

// One verdict of the legend: its label and how many highlighted passages
// carry it.
export interface BriefFactCheckLegendItem {
  verdict: CitationVerdict;
  label: string;
  count: number;
}

// Live check progress is fetched separately from the completed claim marks.
export interface BriefCheckRun {
  id: string;
  status: CheckStatus;
  stopped: boolean;
  progress?: RunProgress | null;
}

export interface BriefFactCheckRead {
  start_disabled_reason?: string | null;
  active_run?: BriefCheckRun | null;
  check: BriefCitationCheck | null;
  brief_version?: number | null;
  current_version?: number | null;
  note?: string;
  changed_sections?: BriefFactCheckSection[];
  legend: BriefFactCheckLegendItem[];
  marks: BriefFactCheckMark[];
}

// A run of a cited excerpt; highlighted when the judge quoted it.
export interface BriefFactCheckSegment {
  text: string;
  highlighted: boolean;
}

// One cited source as the judge read it, for a highlighted passage's card.
export interface BriefFactCheckEvidence {
  citation: number | null;
  label: string;
  title: string;
  page?: number | null;
  section: string;
  doc_id?: string | null;
  chunk_id?: string | null;
  pdf_url?: string | null;
  quoted: boolean;
  segments: BriefFactCheckSegment[];
}

// GET /briefs/{id}/fact-check/{check_id}/passages/{passage_id}: the evidence
// behind one highlighted passage, loaded when its card opens.
export interface BriefFactCheckEvidenceRead {
  passage_id: number;
  verdict: CitationVerdict;
  verdict_label: string;
  evidence: BriefFactCheckEvidence[];
}
