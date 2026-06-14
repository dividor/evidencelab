// Types for the admin Search & AI-Summary evaluation harness (superuser-only).

export type TestCapability = 'search' | 'ai_summary';
export type ExperimentStatus = 'pending' | 'running' | 'completed' | 'failed';
export type ResultStatus = 'pass' | 'fail' | 'error';

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

export interface TestCase {
  id: string;
  dataset_id: string;
  input: Record<string, unknown>;
  expectations: Assertion[];
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
}

export interface SummaryStats {
  total: number;
  passed: number;
  failed: number;
  errored: number;
  pass_rate: number;
  mean_score?: number | null;
  duration_ms: number;
  error?: string;
}

export interface TestExperiment {
  id: string;
  dataset_id: string;
  name: string;
  status: ExperimentStatus;
  config?: Record<string, unknown> | null;
  summary_stats?: SummaryStats | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_by_user_id?: string | null;
  created_at: string;
}

export interface TestResult {
  id: string;
  experiment_id: string;
  test_case_id: string;
  status: ResultStatus;
  score?: number | null;
  actual_output?: Record<string, unknown> | null;
  assertion_results?: AssertionResult[] | null;
  latency_ms?: number | null;
  error_message?: string | null;
  created_at: string;
}

export interface ExperimentDetail extends TestExperiment {
  results: TestResult[];
}
