import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { CoverageNotice } from '../components/CoverageNotice';
import { approximateExtraDocuments } from '../utils/resultsCoverage';
import type { SearchCoverage } from '../types/api';

const concentrated: SearchCoverage = {
  chunks_returned: 50,
  documents_in_results: 6,
  candidate_documents: 184,
  concentrated: true,
};

const distributed: SearchCoverage = {
  chunks_returned: 50,
  documents_in_results: 32,
  candidate_documents: 184,
  concentrated: false,
};

const noop = () => undefined;

const renderNotice = (
  overrides: Partial<React.ComponentProps<typeof CoverageNotice>> = {},
) =>
  render(
    <CoverageNotice
      coverage={concentrated}
      broadenActive={false}
      dismissed={false}
      onBroaden={noop}
      onShowTopDocuments={noop}
      onDismiss={noop}
      {...overrides}
    />,
  );

describe('CoverageNotice', () => {
  it('renders the alert with document counts when results are concentrated', () => {
    renderNotice();
    const status = screen.getByRole('status');
    expect(status).toHaveTextContent('Only 6 documents contain the top-matching excerpts');
    // 184 - 6 = 178, rounded to the nearest ten to avoid false precision.
    expect(status).toHaveTextContent('about 180 more matched with lower relevance');
    expect(screen.getByRole('button', { name: 'Show more documents' })).toBeInTheDocument();
  });

  it('renders nothing when the server did not flag concentration', () => {
    renderNotice({ coverage: distributed });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('renders nothing when there is no coverage (empty-query path)', () => {
    renderNotice({ coverage: null });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('renders nothing after the user dismissed it', () => {
    renderNotice({ dismissed: true });
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('invokes the broaden callback from the action button', () => {
    const onBroaden = jest.fn();
    renderNotice({ onBroaden });
    fireEvent.click(screen.getByRole('button', { name: 'Show more documents' }));
    expect(onBroaden).toHaveBeenCalledTimes(1);
  });

  it('invokes the dismiss callback from the close button', () => {
    const onDismiss = jest.fn();
    renderNotice({ onDismiss });
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss this notice' }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it('shows the confirmation strip with a way back while broadened', () => {
    const onShowTopDocuments = jest.fn();
    renderNotice({
      broadenActive: true,
      coverage: distributed,
      onShowTopDocuments,
    });
    // 184 candidates rounded to 180: the 32 shown are framed as a slice of
    // the matching field, so the alert's count and this state stay coherent.
    expect(screen.getByRole('status')).toHaveTextContent(
      'Showing the top excerpts from 32 of about 180 matching documents',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show only top documents' }));
    expect(onShowTopDocuments).toHaveBeenCalledTimes(1);
    // The alert body and dismiss control belong to the alert state only.
    expect(screen.queryByRole('button', { name: 'Dismiss this notice' })).not.toBeInTheDocument();
  });

  it('shows the confirmation strip even after dismissal (user-initiated mode)', () => {
    renderNotice({ broadenActive: true, dismissed: true, coverage: distributed });
    expect(screen.getByRole('status')).toHaveTextContent('Showing the top excerpts');
  });

  it('never reports fewer matching documents than are on the page', () => {
    // Rounding 22 candidates down to 20 would contradict a page showing 21
    // documents; the total is clamped to the page count.
    renderNotice({
      broadenActive: true,
      coverage: {
        chunks_returned: 42,
        documents_in_results: 21,
        candidate_documents: 22,
        concentrated: false,
      },
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      'from 21 of about 21 matching documents',
    );
  });

  it('uses singular grammar for a single dominating document', () => {
    renderNotice({
      coverage: { ...concentrated, documents_in_results: 1, candidate_documents: 12 },
    });
    expect(screen.getByRole('status')).toHaveTextContent(
      'Only 1 document contains the top-matching excerpts',
    );
    expect(screen.getByRole('status')).toHaveTextContent('about 11 more');
  });
});

describe('approximateExtraDocuments', () => {
  it('keeps small differences exact', () => {
    expect(
      approximateExtraDocuments({ ...concentrated, candidate_documents: 18 }),
    ).toBe(12);
  });

  it('rounds larger differences to the nearest ten', () => {
    expect(approximateExtraDocuments(concentrated)).toBe(180);
  });

  it('never returns a negative count', () => {
    expect(
      approximateExtraDocuments({ ...concentrated, candidate_documents: 3 }),
    ).toBe(0);
  });
});
