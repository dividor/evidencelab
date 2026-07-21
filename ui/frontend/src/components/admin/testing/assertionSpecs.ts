// Specs describing the available assertion types per capability and the
// parameter fields each one needs. Used by the assertion-column form to render
// type-appropriate inputs and to summarise assertions for display.

import type { TestCapability } from '../../../types/testing';

export type AssertionFieldType = 'text' | 'textarea' | 'number' | 'boolean' | 'csv';

export interface AssertionFieldSpec {
  key: string;
  label: string;
  type: AssertionFieldType;
  required?: boolean;
  placeholder?: string;
  // Default value applied when a new assertion column of this type is created.
  default?: string | number | boolean;
}

export interface AssertionTypeSpec {
  type: string;
  label: string;
  fields: AssertionFieldSpec[];
}

const SEARCH_ASSERTIONS: AssertionTypeSpec[] = [
  {
    type: 'result_contains_id',
    label: 'Result contains id',
    fields: [{ key: 'id', label: 'Document id', type: 'text', required: true }],
  },
  {
    type: 'result_in_top_k',
    label: 'Result in top K',
    fields: [
      { key: 'id', label: 'Document id', type: 'text', required: true },
      { key: 'k', label: 'K', type: 'number', required: true },
    ],
  },
  {
    type: 'min_results',
    label: 'Min results',
    fields: [{ key: 'value', label: 'Value', type: 'number', required: true }],
  },
  {
    type: 'max_results',
    label: 'Max results',
    fields: [{ key: 'value', label: 'Value', type: 'number', required: true }],
  },
  {
    type: 'ordering',
    label: 'Ordering',
    fields: [
      {
        key: 'ids',
        label: 'Ordered ids (comma separated)',
        type: 'csv',
        required: true,
        placeholder: 'id-1, id-2, id-3',
      },
    ],
  },
  {
    type: 'field_match',
    label: 'Field match',
    fields: [
      { key: 'field', label: 'Field', type: 'text', required: true },
      { key: 'equals', label: 'Equals', type: 'text' },
      { key: 'contains', label: 'Contains', type: 'text' },
      { key: 'id', label: 'Document id (optional)', type: 'text' },
    ],
  },
];

const AI_SUMMARY_ASSERTIONS: AssertionTypeSpec[] = [
  {
    type: 'contains_text',
    label: 'Contains text',
    fields: [
      { key: 'text', label: 'Text', type: 'text', required: true },
      { key: 'case_insensitive', label: 'Case insensitive', type: 'boolean' },
    ],
  },
  {
    type: 'not_contains_text',
    label: 'Not contains text',
    fields: [{ key: 'text', label: 'Text', type: 'text', required: true }],
  },
  {
    type: 'regex_match',
    label: 'Regex match',
    fields: [{ key: 'pattern', label: 'Pattern', type: 'text', required: true }],
  },
  {
    type: 'min_length',
    label: 'Min length',
    fields: [{ key: 'value', label: 'Value', type: 'number', required: true }],
  },
  {
    type: 'max_length',
    label: 'Max length',
    fields: [{ key: 'value', label: 'Value', type: 'number', required: true }],
  },
  {
    type: 'cites_source',
    label: 'Cites source',
    fields: [{ key: 'source', label: 'Source', type: 'text', required: true }],
  },
  {
    type: 'llm_judge',
    label: 'LLM judge',
    fields: [
      {
        key: 'rubric',
        label: 'Judge prompt',
        type: 'textarea',
        required: true,
        placeholder:
          'Describe what a good answer must contain. The judge returns a 0-1 '
          + 'score and a reason.',
      },
      {
        key: 'threshold',
        label: 'Threshold (0-1)',
        type: 'number',
        required: true,
        default: 1,
      },
    ],
  },
];

export const ASSERTION_SPECS_BY_CAPABILITY: Record<TestCapability, AssertionTypeSpec[]> = {
  search: SEARCH_ASSERTIONS,
  ai_summary: AI_SUMMARY_ASSERTIONS,
};

export const getAssertionSpecs = (capability: TestCapability): AssertionTypeSpec[] =>
  ASSERTION_SPECS_BY_CAPABILITY[capability] ?? [];

export const getAssertionSpec = (
  capability: TestCapability,
  type: string,
): AssertionTypeSpec | undefined => getAssertionSpecs(capability).find((s) => s.type === type);
