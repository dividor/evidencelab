// Inline form to define or edit one assertion "column" (type + params) for the
// experiment's assertion matrix. Reuses the per-field inputs and the
// capability-specific assertion specs.

import React, { useState } from 'react';
import type { Assertion, TestCapability } from '../../../types/testing';
import { getAssertionSpec, getAssertionSpecs } from './assertionSpecs';
import { defaultAssertion, FieldInput } from './assertionFields';

interface AssertionColumnFormProps {
  capability: TestCapability;
  initial?: Assertion | null;
  onSubmit: (assertion: Assertion) => void;
  onCancel: () => void;
}

const AssertionColumnForm: React.FC<AssertionColumnFormProps> = ({
  capability,
  initial,
  onSubmit,
  onCancel,
}) => {
  const specs = getAssertionSpecs(capability);
  const isEdit = Boolean(initial);
  const [assertion, setAssertion] = useState<Assertion>(
    initial || defaultAssertion(capability, specs[0]?.type ?? ''),
  );

  const spec = getAssertionSpec(capability, assertion.type);

  const setType = (type: string) => setAssertion(defaultAssertion(capability, type));
  const setParam = (key: string, value: unknown) =>
    setAssertion((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="testing-column-form">
      <div className="testing-column-form-header">
        <strong>{isEdit ? 'Edit assertion' : 'Add assertion column'}</strong>
      </div>
      <div className="form-group">
        <label>Assertion type</label>
        <select
          value={assertion.type}
          onChange={(e) => setType(e.target.value)}
          disabled={isEdit}
        >
          {specs.map((s) => (
            <option key={s.type} value={s.type}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      {spec && spec.fields.length > 0 && (
        <div className="testing-assertion-fields">
          {spec.fields.map((field) => (
            <FieldInput
              key={field.key}
              field={field}
              assertion={assertion}
              onSet={setParam}
            />
          ))}
        </div>
      )}
      <div className="testing-column-form-actions">
        <button type="button" className="btn-sm btn-cancel" onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          className="btn-sm btn-primary"
          onClick={() => onSubmit(assertion)}
          disabled={!assertion.type}
        >
          {isEdit ? 'Save assertion' : 'Add column'}
        </button>
      </div>
    </div>
  );
};

export default AssertionColumnForm;
