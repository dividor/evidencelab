import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import FacetMultiSelect from '../components/admin/testing/FacetMultiSelect';

describe('FacetMultiSelect', () => {
  test('renders selected values as chips and removes on click', () => {
    const onChange = jest.fn();
    render(
      <FacetMultiSelect
        options={['Kenya', 'Uganda']}
        value={['Kenya']}
        onChange={onChange}
      />,
    );
    expect(screen.getByText('Kenya')).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText('Remove Kenya'));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  test('filters options by the typed term and adds the chosen one', () => {
    const onChange = jest.fn();
    render(
      <FacetMultiSelect
        options={['Kenya', 'Uganda', 'Tanzania']}
        value={[]}
        onChange={onChange}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/type to filter/i), {
      target: { value: 'ken' },
    });
    expect(screen.queryByRole('button', { name: 'Uganda' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Kenya' }));
    expect(onChange).toHaveBeenCalledWith(['Kenya']);
  });

  test('excludes already-selected values from the suggestions', () => {
    render(
      <FacetMultiSelect
        options={['Kenya', 'Uganda']}
        value={['Kenya']}
        onChange={jest.fn()}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText(/type to filter/i), {
      target: { value: 'a' },
    });
    // 'Kenya' is selected (chip only), so only 'Uganda' is offered as a suggestion.
    expect(screen.getByRole('button', { name: 'Uganda' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Kenya' })).not.toBeInTheDocument();
  });
});
