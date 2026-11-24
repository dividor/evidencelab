import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { DocumentsFilterPopover } from '../components/documents/DocumentsFilterPopover';
import { joinFilterValues } from '../utils/filterValues';

// Documents tab filters send several values as one comma-separated string, so a
// value that itself contains a comma (an SDG name, a country, a title) must be
// escaped or the API splits it into pieces that match nothing.

const SDG16 = 'SDG16 - Peace, Justice and Strong Institutions';
const SDG9 = 'SDG9 - Industry, Innovation and Infrastructure';
const SDG1 = 'SDG1 - No Poverty';
const COMMA_TITLE = 'Country evaluation, 2016-2020';
const PLAIN_TITLE = 'Annual report';

const renderPopover = (
  column: string,
  options: string[],
  columnFilters: Record<string, string> = {},
) => {
  const onApplyFilter = jest.fn();
  const onClearFilter = jest.fn();
  const onClose = jest.fn();
  render(
    <DocumentsFilterPopover
      activeFilterColumn={column}
      filterPopoverPosition={{ top: 0, left: 0 }}
      tempColumnFilters={{}}
      columnFilters={columnFilters}
      onTempFilterChange={jest.fn()}
      onApplyFilter={onApplyFilter}
      onClearFilter={onClearFilter}
      hasActiveFilter={(name) => name in columnFilters}
      getCategoricalOptions={() => options}
      onClose={onClose}
      dataSourceConfig={{ pipeline: { tag: { taxonomies: { sdg: {} } } } }}
    />,
  );
  return { onApplyFilter, onClearFilter, onClose };
};

describe('Documents filter values that contain commas', () => {
  test('ticking a taxonomy value with a comma applies it escaped and whole', () => {
    const { onApplyFilter } = renderPopover('sdg', [SDG1, SDG9, SDG16]);

    fireEvent.click(screen.getByRole('checkbox', { name: SDG16 }));
    fireEvent.click(screen.getByRole('checkbox', { name: SDG9 }));
    fireEvent.click(screen.getByRole('button', { name: /^Apply \(2\)/ }));

    expect(onApplyFilter).toHaveBeenCalledWith('sdg', joinFilterValues([SDG16, SDG9]));
    expect(onApplyFilter.mock.calls[0][1]).toBe(
      'SDG16 - Peace\\, Justice and Strong Institutions,SDG9 - Industry\\, Innovation and Infrastructure',
    );
  });

  test('reopening the filter shows each applied comma value ticked once', () => {
    renderPopover('sdg', [SDG1, SDG9, SDG16], { sdg: joinFilterValues([SDG16]) });

    expect(screen.getByRole('checkbox', { name: SDG16 })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: SDG9 })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: SDG1 })).not.toBeChecked();
    expect(screen.getByRole('button', { name: /^Apply \(1\)/ })).toBeInTheDocument();
  });

  test('titles with commas are applied as separate whole titles', () => {
    const { onApplyFilter } = renderPopover('title', [COMMA_TITLE, PLAIN_TITLE]);

    fireEvent.click(screen.getByRole('checkbox', { name: 'Select all' }));
    fireEvent.click(screen.getByRole('button', { name: /^Apply \(2\)/ }));

    expect(onApplyFilter).toHaveBeenCalledWith(
      'title',
      'Country evaluation\\, 2016-2020,Annual report',
    );
  });

  test('a filter link written before escaping still restores plain values', () => {
    renderPopover('organization', ['UNDP', 'WFP', 'UNICEF'], { organization: 'UNDP,WFP' });

    expect(screen.getByRole('checkbox', { name: 'UNDP' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'WFP' })).toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'UNICEF' })).not.toBeChecked();
  });
});
