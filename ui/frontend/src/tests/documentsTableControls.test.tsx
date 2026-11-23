import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { DocumentsTableControls } from '../components/documents/DocumentsTableControls';

const SEARCH_PLACEHOLDER = 'Search by title';
const REFRESH = 'Refresh table';
const EXPORT = 'Export to Excel';

const baseProps = {
  filterText: '',
  onFilterTextChange: jest.fn(),
  selectedCategory: null,
  chartView: 'year',
  currentPage: 1,
  pageSize: 10,
  totalCount: 333,
  loadingTable: false,
  onRefresh: jest.fn(),
  onClearCategory: jest.fn(),
};

describe('DocumentsTableControls layout hooks', () => {
  test('keeps the count and buttons in one styled group after the title search', () => {
    const { container } = render(<DocumentsTableControls {...baseProps} onExport={jest.fn()} />);

    const controls = container.querySelector('.table-controls') as HTMLElement;
    const search = screen.getByPlaceholderText(SEARCH_PLACEHOLDER);
    const actions = container.querySelector('.table-controls-actions') as HTMLElement;

    // The tablet CSS gives the search and this group a full row each, so both
    // must be direct children of the controls row, search first.
    expect(actions).not.toBeNull();
    expect(Array.from(controls.children)).toEqual([search, actions]);
    // Layout lives in App.css now; an inline style would beat the media queries.
    expect(actions.getAttribute('style')).toBeNull();

    expect(actions.querySelector('.table-count')).toHaveTextContent(
      'Showing 1-10 of 333 documents',
    );
    expect(actions).toContainElement(screen.getByRole('button', { name: EXPORT }));
    expect(actions).toContainElement(screen.getByRole('button', { name: REFRESH }));
  });

  test('puts the clear-category button between the search and the group', () => {
    const onClearCategory = jest.fn();
    const { container } = render(
      <DocumentsTableControls {...baseProps} selectedCategory="2024" onClearCategory={onClearCategory} />,
    );

    const controls = container.querySelector('.table-controls') as HTMLElement;
    const clear = screen.getByRole('button', { name: 'Clear Category Filter: 2024' });
    expect(controls.children[1]).toBe(clear);
    expect(controls.children[2]).toHaveClass('table-controls-actions');
    expect(screen.getByText(/filtered by year/)).toBeInTheDocument();

    fireEvent.click(clear);
    expect(onClearCategory).toHaveBeenCalledTimes(1);
  });

  test('wires the search box, refresh and export to their handlers', () => {
    const onFilterTextChange = jest.fn();
    const onRefresh = jest.fn();
    const onExport = jest.fn();
    render(
      <DocumentsTableControls
        {...baseProps}
        onFilterTextChange={onFilterTextChange}
        onRefresh={onRefresh}
        onExport={onExport}
      />,
    );

    fireEvent.change(screen.getByPlaceholderText(SEARCH_PLACEHOLDER), { target: { value: 'school' } });
    fireEvent.click(screen.getByRole('button', { name: REFRESH }));
    fireEvent.click(screen.getByRole('button', { name: EXPORT }));

    expect(onFilterTextChange).toHaveBeenCalledWith('school');
    expect(onRefresh).toHaveBeenCalledTimes(1);
    expect(onExport).toHaveBeenCalledTimes(1);
  });

  test('omits the export button when there is nothing to export', () => {
    render(<DocumentsTableControls {...baseProps} />);
    expect(screen.queryByRole('button', { name: EXPORT })).not.toBeInTheDocument();
  });
});
