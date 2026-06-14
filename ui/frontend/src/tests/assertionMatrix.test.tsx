import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import AssertionMatrix from '../components/admin/testing/AssertionMatrix';
import type { AssertionMatrix as MatrixValue, TestCase } from '../types/testing';

const cases: TestCase[] = [
  { id: 'c1', dataset_id: 'd1', input: { query: 'alpha' }, created_at: '', updated_at: '' },
  { id: 'c2', dataset_id: 'd1', input: { query: 'beta' }, created_at: '', updated_at: '' },
];

const Harness: React.FC<{ initial: MatrixValue }> = ({ initial }) => {
  const [value, setValue] = React.useState<MatrixValue>(initial);
  return (
    <AssertionMatrix capability="search" cases={cases} value={value} onChange={setValue} />
  );
};

describe('AssertionMatrix', () => {
  test('renders a row per case and the add-assertion control', () => {
    render(<Harness initial={{ columns: [], cases: {} }} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByText('beta')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\+ Assertion/i })).toBeInTheDocument();
  });

  test('adding an assertion column shows it as a header applied to cases', () => {
    render(<Harness initial={{ columns: [], cases: {} }} />);
    fireEvent.click(screen.getByRole('button', { name: /\+ Assertion/i }));
    fireEvent.click(screen.getByRole('button', { name: /Add column/i }));
    // The new column's header summarises the assertion type (default first spec).
    expect(screen.getByText(/result_contains_id/)).toBeInTheDocument();
  });

  test('does not crash on a legacy per-case value shape', () => {
    // Old drafts stored {caseId: [assertions]} which has no columns/cases keys.
    const legacy = { c1: [{ type: 'min_results', value: 1 }] } as unknown as MatrixValue;
    render(<Harness initial={legacy} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\+ Assertion/i })).toBeInTheDocument();
  });

  test('disabling a row marks it inactive and disables its cells', () => {
    const initial: MatrixValue = {
      columns: [{ type: 'min_results', value: 1 }],
      cases: {
        c1: { active: true, cols: [true] },
        c2: { active: true, cols: [true] },
      },
    };
    render(<Harness initial={initial} />);
    const alpha = screen.getByText('alpha');
    const rowLabel = alpha.closest('label') as HTMLLabelElement;
    const rowCheckbox = rowLabel.querySelector('input') as HTMLInputElement;
    fireEvent.click(rowCheckbox); // toggle the case off
    expect(alpha.closest('tr')).toHaveClass('testing-matrix-row-off');
  });
});
