import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { SearchableSelect } from '../components/SearchableSelect';

describe('SearchableSelect', () => {
  test('filters options and toggles selections', () => {
    const onChange = jest.fn();
    render(
      <SearchableSelect
        label="Organizations"
        options={[
          { value: 'UNDP', count: 5 },
          { value: 'UNICEF', count: 2 },
        ]}
        selectedValues={[]}
        onChange={onChange}
      />
    );

    const input = screen.getByPlaceholderText('Search...');
    fireEvent.focus(input);
    fireEvent.change(input, { target: { value: 'un' } });

    expect(screen.getByText('UNDP')).toBeInTheDocument();
    expect(screen.getByText('UNICEF')).toBeInTheDocument();

    fireEvent.click(screen.getByText('UNDP'));
    expect(onChange).toHaveBeenCalledWith(['UNDP']);
  });

  test('removes and clears selected values', () => {
    const onChange = jest.fn();
    render(
      <SearchableSelect
        label="Years"
        options={[{ value: '2024', count: 1 }]}
        selectedValues={['2024']}
        onChange={onChange}
      />
    );

    fireEvent.click(screen.getByLabelText('Remove 2024'));
    expect(onChange).toHaveBeenCalledWith([]);

    fireEvent.click(screen.getByText('Clear all'));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});
