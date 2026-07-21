import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

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

import { BriefTab } from '../components/brief/BriefTab';

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
    expect(screen.getByText('Generate outline')).toBeInTheDocument();
    expect(screen.getByText('Write my own headings')).toBeInTheDocument();
    // The "Try a topic" examples section was removed.
    expect(screen.queryByText('Try a topic')).toBeNull();
  });

  test('"Write my own headings" enters the builder with starter sections, a History rail and a TOC', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));
    // Left rail is the brief History; the TOC carries the structural actions.
    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Contents')).toBeInTheDocument();
    expect(screen.getByText('Add heading')).toBeInTheDocument();
    expect(screen.getByText('Start deep research →')).toBeInTheDocument();
    const titles = screen.getAllByDisplayValue(/Background & definitions|Key findings|Recommendations/);
    expect(titles.length).toBeGreaterThanOrEqual(3);
  });

  test('the History rail is searchable and briefs can be cloned', () => {
    localStorage.setItem(
      'evidencelab_brief_history_v1',
      JSON.stringify([
        { id: 'x1', title: 'Cash transfers', query: 'cash assistance', date: 1, sectionCount: 0, sourceCount: 0, sections: [] },
        { id: 'x2', title: 'School feeding', query: 'nutrition', date: 2, sectionCount: 0, sourceCount: 0, sections: [] },
      ]),
    );
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));

    expect(screen.getByText('Cash transfers')).toBeInTheDocument();
    expect(screen.getByText('School feeding')).toBeInTheDocument();

    // Search filters the list.
    fireEvent.change(screen.getByLabelText('Search briefs'), { target: { value: 'feeding' } });
    expect(screen.queryByText('Cash transfers')).toBeNull();
    expect(screen.getByText('School feeding')).toBeInTheDocument();

    // Clone the visible brief — a "(copy)" is created and opened.
    fireEvent.click(screen.getAllByLabelText('Duplicate this brief')[0]);
    expect(screen.getByDisplayValue('School feeding (copy)')).toBeInTheDocument();
  });

  test('heading numbers are off by default and can be toggled on by the title-row switch', () => {
    const { container } = render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));

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
    fireEvent.click(screen.getByText('Write my own headings'));

    fireEvent.click(screen.getAllByLabelText('Add a sub-heading')[0]);
    const input = screen.getByLabelText('New sub-heading name');
    expect(input).toBeInTheDocument();

    // Empty + blur adds nothing.
    fireEvent.blur(input);
    expect(screen.queryByLabelText('New sub-heading name')).toBeNull();

    // Re-open, type a name, press Enter — now it's added.
    fireEvent.click(screen.getAllByLabelText('Add a sub-heading')[0]);
    const input2 = screen.getByLabelText('New sub-heading name');
    fireEvent.change(input2, { target: { value: 'Enrolment trends' } });
    fireEvent.keyDown(input2, { key: 'Enter' });
    expect(screen.getByDisplayValue('Enrolment trends')).toBeInTheDocument();
  });

  test('"Add heading" prompts for a name and only adds it once entered', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));

    fireEvent.click(screen.getByText('Add heading'));
    const input = screen.getByLabelText('New heading name');
    // Empty + blur adds nothing.
    fireEvent.blur(input);
    expect(screen.queryByLabelText('New heading name')).toBeNull();

    fireEvent.click(screen.getByText('Add heading'));
    const input2 = screen.getByLabelText('New heading name');
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
    fireEvent.click(screen.getByText('Write my own headings'));
    // A different (manual) brief is open, so x1 still has a delete control.
    expect(screen.getByLabelText('Delete this brief')).toBeInTheDocument();
    // Open x1 — now it is the current brief and loses its delete control.
    fireEvent.click(screen.getByText('Open me'));
    expect(screen.queryByLabelText('Delete this brief')).toBeNull();
  });

  test('"Generate outline" title-cases the brief name and headings', async () => {
    mockRequestOutline.mockResolvedValue({
      title: 'cash assistance',
      headings: [
        { title: 'background information', level: 1 },
        { title: 'food security', level: 2 },
      ],
    });
    render(<BriefTab dataSource="wfp" />);
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'cash assistance' } });
    fireEvent.click(screen.getByText('Generate outline'));

    await waitFor(() =>
      expect(screen.getByDisplayValue('Background Information')).toBeInTheDocument(),
    );
    expect(mockRunDeepResearch).toHaveBeenCalled(); // visible deep-research survey
    expect(mockRequestOutline).toHaveBeenCalled();
    expect(mockRequestOutline.mock.calls[0][0]).toMatchObject({ dataSource: 'wfp', topic: 'cash assistance' });
    expect(screen.getByDisplayValue('Food Security')).toBeInTheDocument();
    // Brief name is capitalised too.
    expect(screen.getByDisplayValue('Cash Assistance')).toBeInTheDocument();
  });
});
