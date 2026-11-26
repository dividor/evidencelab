import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import TocValidatorTable from '../components/admin/TocValidatorTable';

test('the column filter opens outside the scrolling table and can be closed', () => {
  const onFilterClick = jest.fn();
  const onCloseFilter = jest.fn();
  const props = {
    documents: [],
    results: new Map(),
    changedIds: new Set<string>(),
    selectedIds: new Set<string>(),
    approvedIds: new Set<string>(),
    onToggle: jest.fn(),
    onTogglePage: jest.fn(),
    allOnPageSelected: false,
    onOpenMetadata: jest.fn(),
    onOpenToc: jest.fn(),
    columnFilters: {},
    filterPosition: { top: 20, left: 160 },
    onFilterClick,
    onApplyFilter: jest.fn(),
    onClearFilter: jest.fn(),
    hasActiveFilter: () => false,
    getCategoricalOptions: () => [],
    onCloseFilter,
  };
  const { rerender } = render(<TocValidatorTable {...props} activeFilterColumn={null} />);
  const scrollArea = screen.getByRole('table').parentElement;
  expect(scrollArea).toHaveClass('admin-table-scroll');

  fireEvent.click(screen.getByRole('button', { name: 'Filter title' }));
  expect(onFilterClick).toHaveBeenCalledWith('title', expect.anything());

  rerender(<TocValidatorTable {...props} activeFilterColumn="title" />);
  const close = screen.getByRole('button', { name: 'Close filter' });
  expect(scrollArea).not.toContainElement(close);
  fireEvent.click(close);
  expect(onCloseFilter).toHaveBeenCalledTimes(1);
});
