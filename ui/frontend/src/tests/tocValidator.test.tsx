import React from 'react';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import type { TocValidationResult } from '../types/api';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  USER_MODULE: true,
  USER_FEEDBACK: false,
}));

// The reused document modals pull heavy deps; the validator only needs to know
// it hands them the right document.
jest.mock('../components/documents/MetadataModal', () => ({
  __esModule: true,
  MetadataModal: ({ isOpen, metadataDoc }: any) =>
    isOpen ? <div data-testid="metadata-modal">{metadataDoc?.map_title}</div> : null,
}));

jest.mock('../components/TocModal', () => ({
  __esModule: true,
  default: ({ isOpen, docId }: any) =>
    isOpen ? <div data-testid="toc-modal">{docId}</div> : null,
}));

const mockGet = jest.fn();
const mockPost = jest.fn();
jest.mock('axios', () => ({
  __esModule: true,
  default: {
    get: (...args: any[]) => mockGet(...args),
    post: (...args: any[]) => mockPost(...args),
  },
}));

import TocValidationResultCell from '../components/admin/TocValidationResultCell';
import TocValidatorManager from '../components/admin/TocValidatorManager';

const DOCS = [
  { doc_id: 'd1', map_title: 'Zambia Country Programme', organization: 'WFP', status: 'indexed', toc: 'x' },
  { doc_id: 'd2', map_title: 'Yemen Emergency Response', organization: 'WFP', status: 'indexed' },
];

const failResult: TocValidationResult = {
  doc_id: 'd1',
  status: 'fail',
  range_start: 14,
  range_end: 56,
  sections_in_range: 17,
  num_excluded: 13,
  excluded_section_types: ['annexes', 'introduction'],
  excluded_sections: [{ title: 'Recommendations', label: 'annexes', page: 50 }],
  reasons: [],
  validated_at: '2026-07-20T10:00:00Z',
  validated_by: 'admin@wfp.org',
};

const renderCell = (result?: TocValidationResult, changed?: boolean) =>
  render(
    <table>
      <tbody>
        <tr>
          <TocValidationResultCell result={result} changed={changed} />
        </tr>
      </tbody>
    </table>
  );

describe('TocValidationResultCell', () => {
  test('shows Not tested when there is no result', () => {
    renderCell(undefined);
    expect(screen.getByText('Not tested')).toBeInTheDocument();
  });

  test('shows fail status with excluded section types', () => {
    renderCell(failResult);
    expect(screen.getByText('Fail')).toBeInTheDocument();
    expect(screen.getByText(/13 excluded sections/)).toBeInTheDocument();
    expect(screen.getByText(/annexes, introduction/)).toBeInTheDocument();
  });

  test('shows pass status with in-range section count', () => {
    renderCell({ ...failResult, status: 'pass', num_excluded: 0, excluded_section_types: [] });
    expect(screen.getByText('Pass')).toBeInTheDocument();
    expect(screen.getByText(/17 sections in range, all included/)).toBeInTheDocument();
  });

  test('shows readable reason when skipped', () => {
    renderCell({ ...failResult, status: 'skipped', reasons: ['missing_metadata_range'] });
    expect(screen.getByText('Skipped')).toBeInTheDocument();
    expect(screen.getByText(/no body page range in metadata/)).toBeInTheDocument();
  });

  test('shows updated badge when result changed in the last run', () => {
    renderCell(failResult, true);
    expect(screen.getByText('updated')).toBeInTheDocument();
  });
});

describe('TocValidatorManager', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/toc-validator/results')) {
        return Promise.resolve({ data: { results: {} } });
      }
      if (url.includes('/documents')) {
        return Promise.resolve({
          data: { documents: DOCS, total: 2, total_pages: 1 },
        });
      }
      return Promise.resolve({ data: {} });
    });
  });

  test('lists documents with a not-tested verdict initially', async () => {
    render(<TocValidatorManager dataSource="wfp" />);
    expect(await screen.findByText('Zambia Country Programme')).toBeInTheDocument();
    expect(screen.getByText('Yemen Emergency Response')).toBeInTheDocument();
    expect(screen.getAllByText('Not tested')).toHaveLength(2);
  });

  test('shows previously stored results on load', async () => {
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/toc-validator/results')) {
        return Promise.resolve({ data: { results: { d1: failResult } } });
      }
      return Promise.resolve({ data: { documents: DOCS, total: 2, total_pages: 1 } });
    });
    render(<TocValidatorManager dataSource="wfp" />);
    expect(await screen.findByText('Fail')).toBeInTheDocument();
    expect(screen.getAllByText('Not tested')).toHaveLength(1);
  });

  test('run button is disabled until documents are selected', async () => {
    render(<TocValidatorManager dataSource="wfp" />);
    await screen.findByText('Zambia Country Programme');
    expect(screen.getByRole('button', { name: /Run validation \(0\)/ })).toBeDisabled();
  });

  test('selecting a document and running validation shows the new verdict', async () => {
    mockPost.mockResolvedValue({ data: { results: [failResult] } });
    render(<TocValidatorManager dataSource="wfp" />);
    await screen.findByText('Zambia Country Programme');

    fireEvent.click(screen.getByLabelText('Select Zambia Country Programme'));
    const runButton = screen.getByRole('button', { name: /Run validation \(1\)/ });
    expect(runButton).toBeEnabled();
    fireEvent.click(runButton);

    await waitFor(() => expect(screen.getByText('Fail')).toBeInTheDocument());
    expect(mockPost).toHaveBeenCalledWith('/api/toc-validator/run', {
      data_source: 'wfp',
      doc_ids: ['d1'],
    });
    // Newly added result is highlighted as changed.
    expect(screen.getByText('updated')).toBeInTheDocument();
  });

  test('select-all-on-page checkbox selects every row', async () => {
    render(<TocValidatorManager dataSource="wfp" />);
    await screen.findByText('Zambia Country Programme');
    fireEvent.click(screen.getByLabelText('Select all documents on this page'));
    expect(screen.getByRole('button', { name: /Run validation \(2\)/ })).toBeEnabled();
  });

  test('opens the metadata modal from the row link', async () => {
    render(<TocValidatorManager dataSource="wfp" />);
    const row = (await screen.findByText('Zambia Country Programme')).closest('tr') as HTMLElement;
    fireEvent.click(within(row).getByText('Metadata'));
    expect(await screen.findByTestId('metadata-modal')).toHaveTextContent(
      'Zambia Country Programme'
    );
  });

  test('opens the contents modal only when the document has a TOC', async () => {
    render(<TocValidatorManager dataSource="wfp" />);
    const withToc = (await screen.findByText('Zambia Country Programme')).closest(
      'tr'
    ) as HTMLElement;
    const withoutToc = screen.getByText('Yemen Emergency Response').closest('tr') as HTMLElement;

    expect(within(withoutToc).queryByText('Contents')).not.toBeInTheDocument();
    fireEvent.click(within(withToc).getByText('Contents'));
    expect(await screen.findByTestId('toc-modal')).toHaveTextContent('d1');
  });

  test('shows an error when the validation run fails', async () => {
    mockPost.mockRejectedValue(new Error('boom'));
    render(<TocValidatorManager dataSource="wfp" />);
    await screen.findByText('Zambia Country Programme');
    fireEvent.click(screen.getByLabelText('Select Zambia Country Programme'));
    fireEvent.click(screen.getByRole('button', { name: /Run validation \(1\)/ }));
    expect(await screen.findByText('Validation run failed.')).toBeInTheDocument();
  });
});
