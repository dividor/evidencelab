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

  test('renders the seed screen with topic input, generate action and examples', () => {
    render(<BriefTab dataSource="wfp" />);
    expect(screen.getByText('Turn a topic into a research brief')).toBeInTheDocument();
    expect(screen.getByLabelText('Topic')).toBeInTheDocument();
    expect(screen.getByText('Generate outline')).toBeInTheDocument();
    expect(screen.getByText('Write my own headings')).toBeInTheDocument();
    expect(
      screen.getByText('What works in cash and voucher assistance in humanitarian crises?'),
    ).toBeInTheDocument();
  });

  test('clicking an example fills the topic field', () => {
    render(<BriefTab dataSource="wfp" />);
    const example = 'How effective are anticipatory action programmes for floods?';
    fireEvent.click(screen.getByText(example));
    expect((screen.getByLabelText('Topic') as HTMLTextAreaElement).value).toBe(example);
  });

  test('"Write my own headings" enters the outline stage with starter sections', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));
    expect(screen.getByText('Outline')).toBeInTheDocument();
    expect(screen.getByText('Start deep research →')).toBeInTheDocument();
    const titles = screen.getAllByDisplayValue(/Background & definitions|Key findings|Recommendations/);
    expect(titles.length).toBeGreaterThanOrEqual(3);
  });

  test('heading numbers are off by default and can be toggled on from the rail', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));

    const railTitle = (el: Element | null): boolean =>
      el?.className === 'brief-rail-item-title';
    const numbered = (_: string, el: Element | null): boolean =>
      railTitle(el) && /^\s*1\.\s/.test(el?.textContent || '');

    const toggle = screen.getByRole('switch', { name: /number headings/i });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    // No "1." prefix on the first outline item by default.
    expect(screen.queryByText(numbered)).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(numbered)).toBeInTheDocument();
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
