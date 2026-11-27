// Shared helpers for editing/summarising a single assertion's parameters.
// Used by the assertion-column form in the experiment editor's matrix.

import React from 'react';
import type { Assertion, TestCapability } from '../../../types/testing';
import { AssertionFieldSpec, getAssertionSpec, judgeCriterionName } from './assertionSpecs';

// Build a fresh assertion of `type`, seeded with its fields' default values.
export const defaultAssertion = (
  capability: TestCapability,
  type: string,
): Assertion => {
  const assertion: Assertion = { type };
  getAssertionSpec(capability, type)?.fields.forEach((f) => {
    if (f.default !== undefined) assertion[f.key] = f.default;
  });
  return assertion;
};

export const valueToInput = (field: AssertionFieldSpec, value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (field.type === 'csv' && Array.isArray(value)) return value.join(', ');
  return String(value);
};

export const inputToValue = (field: AssertionFieldSpec, raw: string): unknown => {
  if (field.type === 'number') {
    const n = Number(raw);
    return raw === '' || Number.isNaN(n) ? raw : n;
  }
  if (field.type === 'csv') {
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }
  return raw;
};

const formatParamValue = (val: unknown): string =>
  Array.isArray(val) ? `[${val.join(', ')}]` : String(val);

export const summarizeAssertion = (assertion: Assertion): string => {
  if (assertion.type === 'llm_judge' || assertion.type === 'brief_writing' || assertion.type === 'brief_factual') {
    return judgeCriterionName(assertion.type, assertion.rubric, assertion.label);
  }
  const params = Object.entries(assertion)
    .filter(([key]) => key !== 'type')
    .map(([key, val]) => `${key}=${formatParamValue(val)}`)
    .join(', ');
  const name = assertion.type.startsWith('brief_') ? getAssertionSpec('brief', assertion.type)?.label || assertion.type : assertion.type;
  return params ? `${name} (${params})` : name;
};

interface FieldInputProps {
  field: AssertionFieldSpec;
  assertion: Assertion;
  onSet: (key: string, value: unknown) => void;
}

export const FieldInput: React.FC<FieldInputProps> = ({ field, assertion, onSet }) => {
  if (field.type === 'boolean') {
    return (
      <div className="form-group testing-config-checkbox">
        <label>
          <input
            type="checkbox"
            checked={Boolean(assertion[field.key])}
            onChange={(e) => onSet(field.key, e.target.checked)}
          />{' '}
          {field.label}
        </label>
      </div>
    );
  }
  if (field.type === 'textarea') {
    return (
      <div className="form-group">
        <label>
          {field.label}
          {field.required ? ' *' : ''}
        </label>
        <textarea
          className="testing-judge-textarea"
          value={valueToInput(field, assertion[field.key])}
          placeholder={field.placeholder}
          onChange={(e) => onSet(field.key, inputToValue(field, e.target.value))}
        />
      </div>
    );
  }
  return (
    <div className="form-group">
      <label>
        {field.label}
        {field.required ? ' *' : ''}
      </label>
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        value={valueToInput(field, assertion[field.key])}
        placeholder={field.placeholder}
        onChange={(e) => onSet(field.key, inputToValue(field, e.target.value))}
      />
    </div>
  );
};
