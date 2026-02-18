import React from 'react';
import { render, screen } from '@testing-library/react';
import { DocumentsTableRow } from '../components/documents/DocumentsTableRow';
import API_BASE_URL from '../config';

// Mock all the cell components
jest.mock('../components/documents/DocumentActionsCell', () => ({
  DocumentActionsCell: () => <>Actions</>,
}));
jest.mock('../components/documents/DocumentChunksCell', () => ({
  DocumentChunksCell: () => <>Chunks</>,
}));
jest.mock('../components/documents/DocumentErrorCell', () => ({
  DocumentErrorCell: () => <>Error</>,
}));
jest.mock('../components/documents/DocumentFormatCell', () => ({
  DocumentFormatCell: () => <>Format</>,
}));
jest.mock('../components/documents/DocumentLinksCell', () => ({
  DocumentLinksCell: () => <>Links</>,
}));
jest.mock('../components/documents/DocumentMetadataCell', () => ({
  DocumentMetadataCell: () => <>Metadata</>,
}));
jest.mock('../components/documents/DocumentStatusCell', () => ({
  DocumentStatusCell: () => <>Status</>,
}));
jest.mock('../components/documents/DocumentsSummaryCell', () => ({
  DocumentsSummaryCell: () => <>Summary</>,
}));
jest.mock('../components/documents/TaxonomyCell', () => ({
  TaxonomyCell: () => <>Taxonomy</>,
}));

describe('DocumentsTableRow - Thumbnail Functionality', () => {
  const mockProps = {
    index: 0,
    onOpenSummary: jest.fn(),
    onOpenTaxonomyModal: jest.fn(),
    onOpenToc: jest.fn(),
    onOpenMetadata: jest.fn(),
    onOpenTimeline: jest.fn(),
    onOpenLogs: jest.fn(),
    onViewChunks: jest.fn(),
    onReprocess: jest.fn(),
    onOpenQueue: jest.fn(),
    reprocessingDocId: null,
    dataSource: 'uneg',
  };

  test('shows thumbnail for indexed document', () => {
    const doc = {
      id: 'test-doc-1',
      doc_id: 'test-doc-1',
      title: 'Test Document',
      status: 'indexed',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const img = container.querySelector('img.doc-title-thumbnail');
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute(
      'src',
      `${API_BASE_URL}/document/test-doc-1/thumbnail?data_source=uneg`
    );
  });

  test('shows thumbnail for parsed document', () => {
    const doc = {
      id: 'test-doc-2',
      doc_id: 'test-doc-2',
      title: 'Parsed Document',
      status: 'parsed',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const img = container.querySelector('img.doc-title-thumbnail');
    expect(img).toBeInTheDocument();
  });

  test('does NOT show thumbnail for downloaded status', () => {
    const doc = {
      id: 'test-doc-3',
      doc_id: 'test-doc-3',
      title: 'Downloaded Document',
      status: 'downloaded',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const img = container.querySelector('img.doc-title-thumbnail');
    expect(img).not.toBeInTheDocument();

    const placeholder = container.querySelector('.doc-title-thumbnail-placeholder');
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toHaveTextContent('No preview');
  });

  test('does NOT show thumbnail for error status', () => {
    const doc = {
      id: 'test-doc-4',
      doc_id: 'test-doc-4',
      title: 'Error Document',
      status: 'parse_error',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const img = container.querySelector('img.doc-title-thumbnail');
    expect(img).not.toBeInTheDocument();

    const placeholder = container.querySelector('.doc-title-thumbnail-placeholder');
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toHaveTextContent('No preview');
  });

  test('shows "No preview" placeholder when thumbnail URL exists but fails to load', () => {
    const doc = {
      id: 'test-doc-5',
      doc_id: 'test-doc-5',
      title: 'Document with Placeholder',
      status: 'indexed',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const placeholder = container.querySelector('.doc-title-thumbnail-placeholder');
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toHaveTextContent('No preview');
  });

  test('uses doc.data_source if provided, falls back to dataSource prop', () => {
    const doc = {
      id: 'test-doc-6',
      doc_id: 'test-doc-6',
      title: 'Document with Custom Data Source',
      status: 'indexed',
      data_source: 'gcf',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} dataSource="uneg" />
        </tbody>
      </table>
    );

    const img = container.querySelector('img.doc-title-thumbnail');
    expect(img).toHaveAttribute(
      'src',
      `${API_BASE_URL}/document/test-doc-6/thumbnail?data_source=gcf`
    );
  });

  test('handles missing doc_id gracefully', () => {
    const doc = {
      title: 'Document without ID',
      status: 'indexed',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const img = container.querySelector('img.doc-title-thumbnail');
    expect(img).not.toBeInTheDocument();

    const placeholder = container.querySelector('.doc-title-thumbnail-placeholder');
    expect(placeholder).toBeInTheDocument();
  });

  test('shows document title alongside thumbnail', () => {
    const doc = {
      id: 'test-doc-7',
      doc_id: 'test-doc-7',
      title: 'Document with Title',
      status: 'indexed',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const titleText = container.querySelector('.doc-title-text');
    expect(titleText).toBeInTheDocument();
    expect(titleText).toHaveTextContent('Document with Title');
  });

  test('shows "Untitled" for documents without title', () => {
    const doc = {
      id: 'test-doc-8',
      doc_id: 'test-doc-8',
      status: 'indexed',
    };

    const { container } = render(
      <table>
        <tbody>
          <DocumentsTableRow doc={doc} {...mockProps} />
        </tbody>
      </table>
    );

    const titleText = container.querySelector('.doc-title-text');
    expect(titleText).toBeInTheDocument();
    expect(titleText).toHaveTextContent('Untitled');
  });
});
