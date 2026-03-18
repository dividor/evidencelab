import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  resolveConfiguredFields,
  getConfiguredFieldKeys,
} from '../components/documents/documentsModalUtils';

jest.mock('react-markdown', () => {
  const React = jest.requireActual('react');
  return {
    __esModule: true,
    default: ({ children }: { children: React.ReactNode }) =>
      React.createElement('div', null, children),
  };
});

import { MetadataModal } from '../components/documents/MetadataModal';

// --- Unit tests for utility functions ---

describe('resolveConfiguredFields', () => {
  const metadata = {
    map_organization: 'UNICEF',
    map_title: 'Test Report',
    map_published_year: '2024',
    map_country: 'Nepal',
    src_geographic_scope: 'Regional',
    sys_page_count: 42,
    full_summary: 'This is a summary.',
    toc_classified: '[H1] Introduction',
  };

  it('resolves unprefixed config keys to map_ metadata keys', () => {
    const panelFields = { organization: 'Organization', title: 'Document Title' };
    const items = resolveConfiguredFields(metadata, panelFields);
    expect(items).toHaveLength(2);
    expect(items[0]).toEqual({
      key: 'map_organization', configKey: 'organization',
      displayKey: 'Organization', value: 'UNICEF',
    });
    expect(items[1]).toEqual({
      key: 'map_title', configKey: 'title',
      displayKey: 'Document Title', value: 'Test Report',
    });
  });

  it('resolves already-prefixed keys (exact match first)', () => {
    const panelFields = { src_geographic_scope: 'Geographic Scope' };
    const items = resolveConfiguredFields(metadata, panelFields);
    expect(items).toHaveLength(1);
    expect(items[0]).toEqual({
      key: 'src_geographic_scope', configKey: 'src_geographic_scope',
      displayKey: 'Geographic Scope', value: 'Regional',
    });
  });

  it('resolves non-prefixed keys like full_summary via exact match', () => {
    const panelFields = { full_summary: 'Summary', toc_classified: 'Table of Contents' };
    const items = resolveConfiguredFields(metadata, panelFields);
    expect(items).toHaveLength(2);
    expect(items[0].key).toBe('full_summary');
    expect(items[0].configKey).toBe('full_summary');
    expect(items[1].key).toBe('toc_classified');
    expect(items[1].configKey).toBe('toc_classified');
  });

  it('resolves sys_-prefixed keys and preserves configKey', () => {
    // Simulates search result metadata where fields are sys_-prefixed
    const sysMetadata = {
      map_organization: 'FAO',
      map_title: 'Test Report',
      sys_full_summary: 'A prefixed summary.',
      sys_toc_classified: '[H1] Chapter 1',
    };
    const panelFields = {
      organization: 'Organization',
      full_summary: 'Summary',
      toc_classified: 'Table of Contents',
    };
    const items = resolveConfiguredFields(sysMetadata, panelFields);
    expect(items).toHaveLength(3);
    // full_summary config key resolves to sys_full_summary metadata key
    const summaryItem = items.find(i => i.configKey === 'full_summary');
    expect(summaryItem).toBeDefined();
    expect(summaryItem!.key).toBe('sys_full_summary');
    expect(summaryItem!.configKey).toBe('full_summary');
    expect(summaryItem!.value).toBe('A prefixed summary.');
    // toc_classified config key resolves to sys_toc_classified metadata key
    const tocItem = items.find(i => i.configKey === 'toc_classified');
    expect(tocItem).toBeDefined();
    expect(tocItem!.key).toBe('sys_toc_classified');
    expect(tocItem!.configKey).toBe('toc_classified');
    expect(tocItem!.value).toBe('[H1] Chapter 1');
  });

  it('preserves config order', () => {
    const panelFields = {
      country: 'Country',
      organization: 'Organization',
      title: 'Document Title',
    };
    const items = resolveConfiguredFields(metadata, panelFields);
    expect(items.map(i => i.displayKey)).toEqual(['Country', 'Organization', 'Document Title']);
  });

  it('skips fields not found in metadata', () => {
    const panelFields = { organization: 'Organization', nonexistent_field: 'Missing' };
    const items = resolveConfiguredFields(metadata, panelFields);
    expect(items).toHaveLength(1);
    expect(items[0].displayKey).toBe('Organization');
  });

  it('skips fields with empty values', () => {
    const metaWithEmpty = { ...metadata, map_language: '' };
    const panelFields = { language: 'Language', organization: 'Organization' };
    const items = resolveConfiguredFields(metaWithEmpty, panelFields);
    expect(items).toHaveLength(1);
    expect(items[0].displayKey).toBe('Organization');
  });

  it('returns empty array for empty config', () => {
    const items = resolveConfiguredFields(metadata, {});
    expect(items).toHaveLength(0);
  });

  it('tries sys_ prefix', () => {
    const panelFields = { page_count: 'Page Count' };
    const items = resolveConfiguredFields(metadata, panelFields);
    expect(items).toHaveLength(1);
    expect(items[0]).toEqual({
      key: 'sys_page_count', configKey: 'page_count',
      displayKey: 'Page Count', value: 42,
    });
  });
});

describe('getConfiguredFieldKeys', () => {
  const metadata = {
    map_organization: 'UNICEF',
    map_title: 'Test Report',
    src_geographic_scope: 'Regional',
    full_summary: 'Summary text',
  };

  it('returns resolved metadata keys', () => {
    const panelFields = { organization: 'Organization', src_geographic_scope: 'Scope' };
    const keys = getConfiguredFieldKeys(metadata, panelFields);
    expect(keys.has('map_organization')).toBe(true);
    expect(keys.has('src_geographic_scope')).toBe(true);
    expect(keys.size).toBe(2);
  });

  it('excludes keys not found in metadata', () => {
    const panelFields = { organization: 'Organization', nonexistent: 'Missing' };
    const keys = getConfiguredFieldKeys(metadata, panelFields);
    expect(keys.size).toBe(1);
    expect(keys.has('map_organization')).toBe(true);
  });

  it('includes non-prefixed keys like full_summary', () => {
    const panelFields = { full_summary: 'Summary' };
    const keys = getConfiguredFieldKeys(metadata, panelFields);
    expect(keys.has('full_summary')).toBe(true);
  });
});

// --- Component rendering tests ---

describe('MetadataModal', () => {
  const baseMetadata = {
    doc_id: 'doc-123',
    map_organization: 'UNICEF',
    map_title: 'Test Report',
    map_published_year: '2024',
    map_country: 'Nepal',
    src_geographic_scope: 'Regional',
    sys_page_count: 42,
    sys_file_format: 'pdf',
  };

  const panelFields = {
    organization: 'Organization',
    title: 'Document Title',
    country: 'Country',
  };

  it('renders configured fields at top when metadataPanelFields provided', () => {
    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={baseMetadata}
        metadataPanelFields={panelFields}
      />
    );
    expect(screen.getByText('Organization')).toBeInTheDocument();
    expect(screen.getByText('UNICEF')).toBeInTheDocument();
    expect(screen.getByText('Document Title')).toBeInTheDocument();
    expect(screen.getByText('Country')).toBeInTheDocument();
  });

  it('renders System Information toggle when configured fields present', () => {
    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={baseMetadata}
        metadataPanelFields={panelFields}
      />
    );
    expect(screen.getByText('System Information')).toBeInTheDocument();
  });

  it('does not render System Information when no metadataPanelFields', () => {
    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={baseMetadata}
      />
    );
    expect(screen.queryByText('System Information')).not.toBeInTheDocument();
  });

  it('expands System Information on click', () => {
    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={baseMetadata}
        metadataPanelFields={panelFields}
      />
    );
    // System info collapsed by default - sub-section headers not visible
    expect(screen.queryByText('Core Fields')).not.toBeInTheDocument();

    // Click toggle
    fireEvent.click(screen.getByText('System Information'));

    // Now sub-section headers should be visible
    expect(screen.getByText('Core Fields')).toBeInTheDocument();
  });

  it('renders View Summary → button when onOpenSummary and full_summary configured', () => {
    const onOpenSummary = jest.fn();
    const metaWithSummary = { ...baseMetadata, full_summary: 'Summary content here' };
    const fieldsWithSummary = { ...panelFields, full_summary: 'Summary' };

    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={metaWithSummary}
        metadataPanelFields={fieldsWithSummary}
        onOpenSummary={onOpenSummary}
      />
    );

    const viewButton = screen.getByText('View Summary →');
    expect(viewButton).toBeInTheDocument();

    fireEvent.click(viewButton);
    expect(onOpenSummary).toHaveBeenCalledWith('Summary content here', 'Test Report', 'doc-123');
  });

  it('renders View Summary → button when full_summary is sys_-prefixed', () => {
    const onOpenSummary = jest.fn();
    // Simulate search result metadata where summary is sys_-prefixed
    const metaWithSysSummary = { ...baseMetadata, sys_full_summary: 'Prefixed summary content' };
    const fieldsWithSummary = { ...panelFields, full_summary: 'Summary' };

    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={metaWithSysSummary}
        metadataPanelFields={fieldsWithSummary}
        onOpenSummary={onOpenSummary}
      />
    );

    const viewButton = screen.getByText('View Summary →');
    expect(viewButton).toBeInTheDocument();

    fireEvent.click(viewButton);
    expect(onOpenSummary).toHaveBeenCalledWith('Prefixed summary content', 'Test Report', 'doc-123');
  });

  it('renders View Contents → button when onOpenToc and toc_classified configured', () => {
    const onOpenToc = jest.fn();
    const metaWithToc = { ...baseMetadata, toc_classified: '[H1] Chapter 1' };
    const fieldsWithToc = { ...panelFields, toc_classified: 'Table of Contents' };

    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={metaWithToc}
        metadataPanelFields={fieldsWithToc}
        onOpenToc={onOpenToc}
      />
    );

    const viewButton = screen.getByText('View Contents →');
    expect(viewButton).toBeInTheDocument();

    fireEvent.click(viewButton);
    expect(onOpenToc).toHaveBeenCalledWith(metaWithToc);
  });

  it('renders View Contents → button when toc_classified is sys_-prefixed', () => {
    const onOpenToc = jest.fn();
    // Simulate search result metadata where toc is sys_-prefixed
    const metaWithSysToc = { ...baseMetadata, sys_toc_classified: '[H1] Chapter 1' };
    const fieldsWithToc = { ...panelFields, toc_classified: 'Table of Contents' };

    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={metaWithSysToc}
        metadataPanelFields={fieldsWithToc}
        onOpenToc={onOpenToc}
      />
    );

    const viewButton = screen.getByText('View Contents →');
    expect(viewButton).toBeInTheDocument();

    fireEvent.click(viewButton);
    expect(onOpenToc).toHaveBeenCalledWith(metaWithSysToc);
  });

  it('renders nothing when isOpen is false', () => {
    const { container } = render(
      <MetadataModal
        isOpen={false}
        onClose={jest.fn()}
        metadataDoc={baseMetadata}
        metadataPanelFields={panelFields}
      />
    );
    expect(container.firstChild).toBeNull();
  });

  it('falls back to all sections when metadataPanelFields is empty', () => {
    render(
      <MetadataModal
        isOpen={true}
        onClose={jest.fn()}
        metadataDoc={baseMetadata}
        metadataPanelFields={{}}
      />
    );
    // Should show section headers directly (no System Information toggle)
    expect(screen.queryByText('System Information')).not.toBeInTheDocument();
    expect(screen.getByText('Core Fields')).toBeInTheDocument();
  });
});
