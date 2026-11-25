import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { SortableHeader } from '../components/documents/SortableHeader';

const renderHeader = (sortField: string, sortDirection: 'asc' | 'desc', onSort = jest.fn()) =>
  render(
    <table>
      <thead>
        <tr>
          <SortableHeader
            columnKey="title"
            label="Title"
            sortField={sortField}
            sortDirection={sortDirection}
            onSort={onSort}
            onFilterClick={jest.fn()}
            hasActiveFilter={() => false}
          />
        </tr>
      </thead>
    </table>,
  );

const sortButton = () => screen.getByRole('button', { name: 'Sort by title' });
const triangle = (direction: 'up' | 'down') =>
  sortButton().querySelector(`.chevron-${direction}`) as SVGPathElement;

describe('SortableHeader', () => {
  test('an unsorted column shows neither triangle as active', () => {
    renderHeader('year', 'asc');

    expect(sortButton()).not.toHaveClass('sorted');
    expect(triangle('up')).not.toHaveClass('active');
    expect(triangle('down')).not.toHaveClass('active');
  });

  test('a column sorted ascending marks the button sorted and the up triangle active', () => {
    renderHeader('title', 'asc');

    expect(sortButton()).toHaveClass('sorted');
    expect(triangle('up')).toHaveClass('active');
    expect(triangle('down')).not.toHaveClass('active');
  });

  test('a column sorted descending marks the down triangle active', () => {
    renderHeader('title', 'desc');

    expect(triangle('down')).toHaveClass('active');
    expect(triangle('up')).not.toHaveClass('active');
  });

  test('the sort button sorts by its column', () => {
    const onSort = jest.fn();
    renderHeader('year', 'asc', onSort);

    fireEvent.click(sortButton());

    expect(onSort).toHaveBeenCalledWith('title');
  });
});
