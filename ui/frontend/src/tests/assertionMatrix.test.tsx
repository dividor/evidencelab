import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import AssertionMatrix from '../components/admin/testing/AssertionMatrix';
import type { AssertionMatrix as MatrixValue, TestCase } from '../types/testing';

const cases: TestCase[] = [
  { id: 'c1', dataset_id: 'd1', input: { query: 'alpha' }, created_at: '', updated_at: '' },
  { id: 'c2', dataset_id: 'd1', input: { query: 'beta' }, created_at: '', updated_at: '' },
];

const MODAL_OVERLAY = '.modal-overlay';

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

  test('clicking + Assertion opens the form in a modal', () => {
    const { container } = render(<Harness initial={{ columns: [], cases: {} }} />);
    expect(container.querySelector(MODAL_OVERLAY)).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /\+ Assertion/i }));
    // The add form is presented in a modal overlay, not inline in the matrix.
    expect(container.querySelector(MODAL_OVERLAY)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Add assertion column/i })).toBeInTheDocument();
  });

  test('cancelling the assertion modal closes it', () => {
    const { container } = render(<Harness initial={{ columns: [], cases: {} }} />);
    fireEvent.click(screen.getByRole('button', { name: /\+ Assertion/i }));
    fireEvent.click(screen.getByRole('button', { name: /Cancel/i }));
    expect(container.querySelector(MODAL_OVERLAY)).toBeNull();
  });

  test('editing an existing column opens the modal in edit mode', () => {
    const initial: MatrixValue = {
      columns: [{ type: 'min_results', value: 1 }],
      cases: {
        c1: { active: true, cols: [true] },
        c2: { active: true, cols: [true] },
      },
    };
    const { container } = render(<Harness initial={initial} />);
    fireEvent.click(screen.getByRole('button', { name: /^Edit$/i }));
    expect(container.querySelector(MODAL_OVERLAY)).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: /Edit assertion/i })).toBeInTheDocument();
  });

  test('does not crash on a legacy per-case value shape', () => {
    // Old drafts stored {caseId: [assertions]} which has no columns/cases keys.
    const legacy = { c1: [{ type: 'min_results', value: 1 }] } as unknown as MatrixValue;
    render(<Harness initial={legacy} />);
    expect(screen.getByText('alpha')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /\+ Assertion/i })).toBeInTheDocument();
  });

  test('typing an llm_judge override enables the cell and stores the text', () => {
    const initial: MatrixValue = {
      columns: [{ type: 'llm_judge', rubric: 'default', threshold: 1 }],
      cases: {
        c1: { active: true, cols: [false], ovr: [''] },
        c2: { active: true, cols: [false], ovr: [''] },
      },
    };
    const AiHarness: React.FC = () => {
      const [value, setValue] = React.useState<MatrixValue>(initial);
      return (
        <AssertionMatrix
          capability="ai_summary"
          cases={cases}
          value={value}
          onChange={setValue}
        />
      );
    };
    render(<AiHarness />);
    const overrides = screen.getAllByPlaceholderText(/Override prompt/i);
    expect(overrides).toHaveLength(2); // one per case for the llm_judge column
    fireEvent.change(overrides[0], { target: { value: 'check Kenya grounding' } });
    expect((overrides[0] as HTMLTextAreaElement).value).toBe('check Kenya grounding');
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
