import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { AiSummaryControls } from '../components/filters/SearchSettingsPanel';

const MAX_LABEL = 'Max results for summary';

const renderControls = (overrides: Partial<React.ComponentProps<typeof AiSummaryControls>> = {}) => {
  const props = {
    summaryLimitResults: true,
    onSummaryLimitResultsChange: jest.fn(),
    summaryMaxResults: 20,
    onSummaryMaxResultsChange: jest.fn(),
    ...overrides,
  };
  render(<AiSummaryControls {...props} />);
  return props;
};

describe('AiSummaryControls', () => {
  test('shows the cap field while the limit is on', () => {
    renderControls();
    expect(screen.getByRole('checkbox')).toBeChecked();
    expect((screen.getByLabelText(MAX_LABEL) as HTMLInputElement).value).toBe('20');
  });

  test('hides the cap field when the limit is off', () => {
    renderControls({ summaryLimitResults: false });
    expect(screen.queryByLabelText(MAX_LABEL)).toBeNull();
  });

  test('reports toggling the limit and editing the cap, clamped to range', () => {
    const props = renderControls();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(props.onSummaryLimitResultsChange).toHaveBeenCalledWith(false);
    const field = screen.getByLabelText(MAX_LABEL);
    fireEvent.change(field, { target: { value: '45' } });
    expect(props.onSummaryMaxResultsChange).toHaveBeenLastCalledWith(45);
    fireEvent.change(field, { target: { value: '0' } });
    expect(props.onSummaryMaxResultsChange).toHaveBeenLastCalledWith(1);
    fireEvent.change(field, { target: { value: '999' } });
    expect(props.onSummaryMaxResultsChange).toHaveBeenLastCalledWith(200);
  });
});
