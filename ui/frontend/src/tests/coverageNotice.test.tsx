import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';

import { CoverageNotice } from '../components/CoverageNotice';
import { approximateMatchingDocuments } from '../utils/resultsCoverage';
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
    // 184 candidates rounded to 180 — the SAME total the broadened state
    // quotes, so the two states can never contradict each other.
    expect(status).toHaveTextContent(
      'Only 6 of about 180 matching documents contain the top-matching excerpts',
    );
    expect(status).toHaveTextContent('the rest matched with lower relevance');
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
      'Only 1 of about 12 matching documents contains the top-matching excerpts',
    );
  });

  it('quotes the same matching total in the alert and the broadened state', () => {
    // The consistency guarantee: both states derive their figure from the
    // same helper, so a user toggling between them sees one number.
    renderNotice();
    const alertText = screen.getByRole('status').textContent ?? '';
    renderNotice({ broadenActive: true, coverage: distributed });
    const broadenedText = screen.getAllByRole('status').pop()?.textContent ?? '';
    const total = String(approximateMatchingDocuments(concentrated));
    expect(alertText).toContain(`about ${total} matching documents`);
    expect(broadenedText).toContain(`about ${total} matching documents`);
  });
});

describe('approximateMatchingDocuments', () => {
  it('keeps small totals exact', () => {
    expect(
      approximateMatchingDocuments({ ...concentrated, candidate_documents: 18 }),
    ).toBe(18);
  });

  it('rounds larger totals to the nearest ten', () => {
    expect(approximateMatchingDocuments(concentrated)).toBe(180);
  });

  it('never reports fewer than the documents on the page', () => {
    expect(
      approximateMatchingDocuments({
        ...concentrated,
        documents_in_results: 21,
        candidate_documents: 22,
      }),
    ).toBe(21);
  });
});
