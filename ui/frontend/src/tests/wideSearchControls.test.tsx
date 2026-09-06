import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { WideSearchControls } from '../components/filters/SearchSettingsPanel';

const PER_DOC_LABEL = 'Max results per document';
const DOCS_LABEL = 'Number of documents';

const renderControls = (overrides: Partial<React.ComponentProps<typeof WideSearchControls>> = {}) => {
  const props = {
    wideSearch: false,
    onWideSearchToggle: jest.fn(),
    wideGroupSize: 5,
    onWideGroupSizeChange: jest.fn(),
    wideLimit: 20,
    onWideLimitChange: jest.fn(),
    ...overrides,
  };
  render(<WideSearchControls {...props} />);
  return props;
};

describe('WideSearchControls', () => {
  test('shows only the checkbox until wide search is on', () => {
    renderControls();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
    expect(screen.queryByLabelText(PER_DOC_LABEL)).toBeNull();
    expect(screen.queryByLabelText(DOCS_LABEL)).toBeNull();
  });

  test('checking the box reports the change', () => {
    const props = renderControls();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(props.onWideSearchToggle).toHaveBeenCalledWith(true);
  });

  test('when on, both fields appear with their values and report edits', () => {
    const props = renderControls({ wideSearch: true, wideGroupSize: 3, wideLimit: 40 });
    const perDoc = screen.getByLabelText(PER_DOC_LABEL) as HTMLInputElement;
    const docs = screen.getByLabelText(DOCS_LABEL) as HTMLInputElement;
    expect(perDoc.value).toBe('3');
    expect(docs.value).toBe('40');

    fireEvent.change(perDoc, { target: { value: '7' } });
    expect(props.onWideGroupSizeChange).toHaveBeenCalledWith(7);
    fireEvent.change(docs, { target: { value: '60' } });
    expect(props.onWideLimitChange).toHaveBeenCalledWith(60);
  });

  test('clamps values into range and ignores non-numbers', () => {
    const props = renderControls({ wideSearch: true });
    const perDoc = screen.getByLabelText(PER_DOC_LABEL);
    fireEvent.change(perDoc, { target: { value: '0' } });
    expect(props.onWideGroupSizeChange).toHaveBeenLastCalledWith(1);
    fireEvent.change(perDoc, { target: { value: '999' } });
    expect(props.onWideGroupSizeChange).toHaveBeenLastCalledWith(50);
    fireEvent.change(perDoc, { target: { value: '' } });
    expect(props.onWideGroupSizeChange).toHaveBeenCalledTimes(2);
  });
});
