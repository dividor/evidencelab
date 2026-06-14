import React, { useState } from 'react';
import type { Assertion, TestCapability } from '../../../types/testing';
import {
  AssertionFieldSpec,
  getAssertionSpec,
  getAssertionSpecs,
} from './assertionSpecs';

interface AssertionBuilderProps {
  capability: TestCapability;
  assertions: Assertion[];
  onChange: (assertions: Assertion[]) => void;
}

/* ------------------------------------------------------------------ */
/*  Value coercion between form inputs and assertion params           */
/* ------------------------------------------------------------------ */

const valueToInput = (field: AssertionFieldSpec, value: unknown): string => {
  if (value === null || value === undefined) return '';
  if (field.type === 'csv' && Array.isArray(value)) return value.join(', ');
  return String(value);
};

const inputToValue = (field: AssertionFieldSpec, raw: string): unknown => {
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

const summarizeAssertion = (assertion: Assertion): string => {
  const params = Object.entries(assertion)
    .filter(([key]) => key !== 'type')
    .map(([key, val]) => `${key}=${formatParamValue(val)}`)
    .join(', ');
  return params ? `${assertion.type} (${params})` : assertion.type;
};

/* ------------------------------------------------------------------ */
/*  Single field input                                                */
/* ------------------------------------------------------------------ */

interface FieldInputProps {
  field: AssertionFieldSpec;
  assertion: Assertion;
  onSet: (key: string, value: unknown) => void;
}

const FieldInput: React.FC<FieldInputProps> = ({ field, assertion, onSet }) => {
  if (field.type === 'boolean') {
    return (
      <label className="testing-assertion-checkbox">
        <input
          type="checkbox"
          checked={Boolean(assertion[field.key])}
          onChange={(e) => onSet(field.key, e.target.checked)}
        />
        {field.label}
      </label>
    );
  }
  return (
    <label className="testing-assertion-field">
      <span>{field.label}{field.required ? ' *' : ''}</span>
      <input
        type={field.type === 'number' ? 'number' : 'text'}
        value={valueToInput(field, assertion[field.key])}
        placeholder={field.placeholder}
        onChange={(e) => onSet(field.key, inputToValue(field, e.target.value))}
      />
    </label>
  );
};

/* ------------------------------------------------------------------ */
/*  Main builder                                                      */
/* ------------------------------------------------------------------ */

const AssertionBuilder: React.FC<AssertionBuilderProps> = ({
  capability,
  assertions,
  onChange,
}) => {
  const specs = getAssertionSpecs(capability);
  const [draftType, setDraftType] = useState<string>(specs[0]?.type ?? '');

  const addAssertion = () => {
    if (!draftType) return;
    onChange([...assertions, { type: draftType }]);
  };

  const removeAssertion = (index: number) => {
    onChange(assertions.filter((_, i) => i !== index));
  };

  const setParam = (index: number, key: string, value: unknown) => {
    const next = assertions.map((a, i) => (i === index ? { ...a, [key]: value } : a));
    onChange(next);
  };

  return (
    <div className="testing-assertion-builder">
      <div className="testing-assertion-list">
        {assertions.length === 0 && (
          <p className="text-muted" style={{ margin: 0 }}>No assertions yet.</p>
        )}
        {assertions.map((assertion, index) => {
          const spec = getAssertionSpec(capability, assertion.type);
          return (
            <div key={index} className="testing-assertion-row">
              <div className="testing-assertion-row-header">
                <strong>{summarizeAssertion(assertion)}</strong>
                <button
                  type="button"
                  className="btn-sm btn-danger"
                  onClick={() => removeAssertion(index)}
                >
                  Remove
                </button>
              </div>
              {spec ? (
                <div className="testing-assertion-fields">
                  {spec.fields.map((field) => (
                    <FieldInput
                      key={field.key}
                      field={field}
                      assertion={assertion}
                      onSet={(key, value) => setParam(index, key, value)}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-muted" style={{ margin: 0 }}>
                  Unknown assertion type for this capability.
                </p>
              )}
            </div>
          );
        })}
      </div>

      <div className="testing-assertion-add">
        <select value={draftType} onChange={(e) => setDraftType(e.target.value)}>
          {specs.map((spec) => (
            <option key={spec.type} value={spec.type}>
              {spec.label}
            </option>
          ))}
        </select>
        <button type="button" className="btn-sm btn-primary" onClick={addAssertion}>
          + Add assertion
        </button>
      </div>
    </div>
  );
};

export default AssertionBuilder;
