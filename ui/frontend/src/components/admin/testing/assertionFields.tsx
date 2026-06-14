// Shared helpers for editing/summarising a single assertion's parameters.
// Used by the assertion-column form in the experiment editor's matrix.

import React from 'react';
import type { Assertion } from '../../../types/testing';
import { AssertionFieldSpec } from './assertionSpecs';

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
  const params = Object.entries(assertion)
    .filter(([key]) => key !== 'type')
    .map(([key, val]) => `${key}=${formatParamValue(val)}`)
    .join(', ');
  return params ? `${assertion.type} (${params})` : assertion.type;
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
