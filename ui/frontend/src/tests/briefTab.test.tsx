import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// Mock config so no real API base/key is needed.
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: 'test-key',
  BRIEF_ENABLED: true,
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

  test('"Write my own headings" enters the builder with starter sections and a saved-briefs rail', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));
    // Left rail now shows saved briefs; the document carries the structural actions.
    expect(screen.getByText('Saved briefs')).toBeInTheDocument();
    expect(screen.getByText('Add heading')).toBeInTheDocument();
    expect(screen.getByText('Start deep research →')).toBeInTheDocument();
    const titles = screen.getAllByDisplayValue(/Background & definitions|Key findings|Recommendations/);
    expect(titles.length).toBeGreaterThanOrEqual(3);
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

  test('"Add heading" appends a new editable heading to the document', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));
    const before = screen.getAllByDisplayValue(/.+/).length;
    fireEvent.click(screen.getByText('Add heading'));
    expect(screen.getByDisplayValue('New heading')).toBeInTheDocument();
    const after = screen.getAllByDisplayValue(/.+/).length;
    expect(after).toBe(before + 1);
  });

  test('"Generate outline" surveys the document library then renders grounded headings', async () => {
    mockRequestOutline.mockResolvedValue({
      title: 'cash assistance',
      headings: [
        { title: 'Background', level: 1 },
        { title: 'Food security', level: 2 },
      ],
    });
    render(<BriefTab dataSource="wfp" />);
    fireEvent.change(screen.getByLabelText('Topic'), { target: { value: 'cash assistance' } });
    fireEvent.click(screen.getByText('Generate outline'));

    await waitFor(() => expect(screen.getByDisplayValue('Background')).toBeInTheDocument());
    expect(mockRunDeepResearch).toHaveBeenCalled(); // visible deep-research survey
    expect(mockRequestOutline).toHaveBeenCalled();
    expect(mockRequestOutline.mock.calls[0][0]).toMatchObject({ dataSource: 'wfp', topic: 'cash assistance' });
    expect(screen.getByDisplayValue('Food security')).toBeInTheDocument();
  });
});
