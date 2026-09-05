import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { BriefTab } from '../components/brief/BriefTab';

// Mock config so no real API base is needed. (briefStream is mocked below, so
// the API key is never read here — omit it to avoid a detect-secrets false hit.)
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: false,
}));

// Brief reads auth to scope saved-brief history; anonymous in tests.
jest.mock('../hooks/useAuth', () => ({
  useAuth: () => ({ user: null }),
}));

// Mock the data layer so the tab never hits the network.
const mockRequestOutline = jest.fn();
const mockResearchSection = jest.fn();
const mockRunDeepResearch = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  requestBriefOutline: (...args: unknown[]) => mockRequestOutline(...args),
  researchBriefSection: (...args: unknown[]) => mockResearchSection(...args),
  runDeepResearch: (...args: unknown[]) => mockRunDeepResearch(...args),
}));

const GENERATE_OUTLINE = 'Generate outline';
const WRITE_OWN_HEADINGS = 'Write my own headings';
const ADD_HEADING = 'Add heading';
const NEW_HEADING_NAME = 'New heading name';
const NEW_SUB_HEADING_NAME = 'New sub-heading name';
const CASH_TRANSFERS = 'Cash transfers';
const CASH_ASSISTANCE = 'cash assistance';
const SCHOOL_FEEDING = 'School feeding';

describe('BriefTab (Document Builder)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    // Default: the deep-research survey resolves immediately with no sources.
    mockRunDeepResearch.mockImplementation(async ({ handlers }: any) => {
      handlers.onSources([]);
      handlers.onDone({ content: '', sources: [] });
    });
  });

  test('renders the seed screen with topic input and generate action', () => {
    render(<BriefTab dataSource="wfp" />);
    expect(screen.getByText('Turn a topic into a research brief')).toBeInTheDocument();
    expect(screen.getByLabelText('Topic')).toBeInTheDocument();
    expect(screen.getByText(GENERATE_OUTLINE)).toBeInTheDocument();
    expect(screen.getByText(WRITE_OWN_HEADINGS)).toBeInTheDocument();
    // The "Try a topic" examples section was removed.
    expect(screen.queryByText('Try a topic')).toBeNull();
  });

  test('"Write my own headings" enters the builder with starter sections, a History rail and a TOC', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(WRITE_OWN_HEADINGS));
    // Left rail is the brief History; the TOC carries the structural actions.
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Contents')).toBeInTheDocument();
    expect(screen.getByText(ADD_HEADING)).toBeInTheDocument();
    expect(screen.getByText('Start deep research →')).toBeInTheDocument();
    const titles = screen.getAllByDisplayValue(/Background & definitions|Key findings|Recommendations/);
    expect(titles.length).toBeGreaterThanOrEqual(3);
  });

  test('the History rail is searchable and briefs can be cloned', () => {
    localStorage.setItem(
      'evidencelab_brief_history_v1',
      JSON.stringify([
        { id: 'x1', title: CASH_TRANSFERS, query: CASH_ASSISTANCE, date: 1, sectionCount: 0, sourceCount: 0, sections: [] },
        { id: 'x2', title: SCHOOL_FEEDING, query: 'nutrition', date: 2, sectionCount: 0, sourceCount: 0, sections: [] },
      ]),
    );
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(WRITE_OWN_HEADINGS));

    expect(screen.getByText(CASH_TRANSFERS)).toBeInTheDocument();
    expect(screen.getByText(SCHOOL_FEEDING)).toBeInTheDocument();

    // Search filters the list.
    fireEvent.change(screen.getByLabelText('Search briefs'), { target: { value: 'feeding' } });
    expect(screen.queryByText(CASH_TRANSFERS)).toBeNull();
    expect(screen.getByText(SCHOOL_FEEDING)).toBeInTheDocument();

    // Clone the visible brief — a "(copy)" is created and opened.
    fireEvent.click(screen.getAllByLabelText('Duplicate this brief')[0]);
    expect(screen.getByDisplayValue('School feeding (copy)')).toBeInTheDocument();
  });

  test('heading numbers are off by default and can be toggled on by the title-row switch', () => {
    const { container } = render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(WRITE_OWN_HEADINGS));

    const toggle = screen.getByRole('switch', { name: /number headings/i });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    // No number badge rendered before the headings by default.
    expect(container.querySelector('.brief-doc-section-num')).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    const nums = Array.from(container.querySelectorAll('.brief-doc-section-num')).map(
      (n) => n.textContent,
    );
    expect(nums).toContain('1');
  });

  test('adding a sub-heading prompts for a name and only adds it once entered', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(WRITE_OWN_HEADINGS));

    fireEvent.click(screen.getAllByLabelText('Add a sub-heading')[0]);
    const input = screen.getByLabelText(NEW_SUB_HEADING_NAME);
    expect(input).toBeInTheDocument();

    // Empty + blur adds nothing.
    fireEvent.blur(input);
    expect(screen.queryByLabelText(NEW_SUB_HEADING_NAME)).toBeNull();

    // Re-open, type a name, press Enter — now it's added.
    fireEvent.click(screen.getAllByLabelText('Add a sub-heading')[0]);
    const input2 = screen.getByLabelText(NEW_SUB_HEADING_NAME);
    fireEvent.change(input2, { target: { value: 'Enrolment trends' } });
    fireEvent.keyDown(input2, { key: 'Enter' });
    expect(screen.getByDisplayValue('Enrolment trends')).toBeInTheDocument();
  });

  test('"Add heading" prompts for a name and only adds it once entered', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(WRITE_OWN_HEADINGS));

    fireEvent.click(screen.getByText(ADD_HEADING));
    const input = screen.getByLabelText(NEW_HEADING_NAME);
    // Empty + blur adds nothing.
    fireEvent.blur(input);
    expect(screen.queryByLabelText(NEW_HEADING_NAME)).toBeNull();

    fireEvent.click(screen.getByText(ADD_HEADING));
    const input2 = screen.getByLabelText(NEW_HEADING_NAME);
    fireEvent.change(input2, { target: { value: 'Annexes' } });
    fireEvent.keyDown(input2, { key: 'Enter' });
    expect(screen.getByDisplayValue('Annexes')).toBeInTheDocument();
  });

  test('the brief currently open cannot be deleted from History', () => {
    localStorage.setItem(
      'evidencelab_brief_history_v1',
      JSON.stringify([
        { id: 'x1', title: 'Open me', query: 'q', date: 1, sectionCount: 0, sourceCount: 0, sections: [] },
      ]),
    );
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText(WRITE_OWN_HEADINGS));
    // A different (manual) brief is open, so x1 still has a delete control.
    expect(screen.getByLabelText('Delete this brief')).toBeInTheDocument();
    // Open x1 — now it is the current brief and loses its delete control.
    fireEvent.click(screen.getByText('Open me'));
    expect(screen.queryByLabelText('Delete this brief')).toBeNull();
  });

  test('"Generate outline" title-cases the brief name and headings', async () => {
    mockRequestOutline.mockResolvedValue({
      title: CASH_ASSISTANCE,
      headings: [
        { title: 'background information', level: 1 },
        { title: 'food security', level: 2 },
      ],
    });
    render(<BriefTab dataSource="wfp" />);
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: CASH_ASSISTANCE } });
    fireEvent.click(screen.getByText(GENERATE_OUTLINE));

    await waitFor(() =>
      expect(screen.getByDisplayValue('Background Information')).toBeInTheDocument(),
    );
    expect(mockRunDeepResearch).toHaveBeenCalled(); // visible deep-research survey
    expect(mockRequestOutline).toHaveBeenCalled();
    expect(mockRequestOutline.mock.calls[0][0]).toMatchObject({ dataSource: 'wfp', topic: CASH_ASSISTANCE });
    expect(screen.getByDisplayValue('Food Security')).toBeInTheDocument();
    // Brief name is capitalised too.
    expect(screen.getByDisplayValue('Cash Assistance')).toBeInTheDocument();
  });

  test('the outline-generation panel has an x that stops it and returns to the form', async () => {
    // The survey hangs until aborted, as a real stream would.
    mockRunDeepResearch.mockImplementation(
      ({ signal }: { signal: AbortSignal }) =>
        new Promise<void>((_, reject) => {
          signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
        }),
    );
    render(<BriefTab dataSource="wfp" />);
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: CASH_ASSISTANCE } });
    fireEvent.click(screen.getByText(GENERATE_OUTLINE));
    expect(await screen.findByText('Deep research in progress')).toBeInTheDocument();
    expect(mockRunDeepResearch).toHaveBeenCalledTimes(1);
    const { signal } = mockRunDeepResearch.mock.calls[0][0];

    fireEvent.click(screen.getByRole('button', { name: 'Stop generating' }));

    expect(signal.aborted).toBe(true);
    await waitFor(() =>
      expect(screen.getByText('Turn a topic into a research brief')).toBeInTheDocument(),
    );
    // The topic is kept so the user can adjust and retry, and no error is shown.
    expect(screen.getByLabelText('Topic')).toHaveValue(CASH_ASSISTANCE);
    expect(mockRequestOutline).not.toHaveBeenCalled();
    expect(screen.queryByText(/could not generate|abort/i)).toBeNull();
  });
});
