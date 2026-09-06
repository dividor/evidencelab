import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { GroupByDocumentControl } from '../components/filters/SearchSettingsPanel';

describe('GroupByDocumentControl', () => {
  test('renders the checkbox with its label and current value', () => {
    render(<GroupByDocumentControl groupByDocument onGroupByDocumentToggle={jest.fn()} />);
    expect(screen.getByRole('checkbox', { name: /Group by document/ })).toBeChecked();
  });

  test('reports a change', () => {
    const onToggle = jest.fn();
    render(<GroupByDocumentControl groupByDocument={false} onGroupByDocumentToggle={onToggle} />);
    fireEvent.click(screen.getByRole('checkbox'));
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});
