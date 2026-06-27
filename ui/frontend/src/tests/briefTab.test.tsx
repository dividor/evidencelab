import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// Mock config so no real API base/key is needed.
jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: 'test-key',
  BRIEF_ENABLED: true,
}));

// Mock the data layer so the tab never hits the network.
const mockRequestOutline = jest.fn();
const mockResearchSection = jest.fn();
jest.mock('../utils/briefStream', () => ({
  __esModule: true,
  requestBriefOutline: (...args: unknown[]) => mockRequestOutline(...args),
  researchBriefSection: (...args: unknown[]) => mockResearchSection(...args),
}));

import { BriefTab } from '../components/brief/BriefTab';

describe('BriefTab (Document Builder)', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
  });

  test('renders the seed screen with generate action and examples', () => {
    render(<BriefTab dataSource="wfp" />);
    expect(screen.getByText('Turn a question into a research brief')).toBeInTheDocument();
    expect(screen.getByText('✦ Generate outline')).toBeInTheDocument();
    expect(screen.getByText('Write my own headings')).toBeInTheDocument();
    expect(
      screen.getByText('What works in cash and voucher assistance in humanitarian crises?'),
    ).toBeInTheDocument();
  });

  test('clicking an example fills the question textarea', () => {
    render(<BriefTab dataSource="wfp" />);
    const example = 'How effective are anticipatory action programmes for floods?';
    fireEvent.click(screen.getByText(example));
    const textarea = screen.getByLabelText('What is the brief about?') as HTMLTextAreaElement;
    expect(textarea.value).toBe(example);
  });

  test('"Write my own headings" enters the outline stage with starter sections', () => {
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('Write my own headings'));
    expect(screen.getByText('Outline')).toBeInTheDocument();
    expect(screen.getByText('Start deep research →')).toBeInTheDocument();
    // Starter section titles appear as editable inputs in the document.
    const titles = screen.getAllByDisplayValue(/Background & definitions|Key findings|Recommendations/);
    expect(titles.length).toBeGreaterThanOrEqual(3);
  });

  test('"Generate outline" calls the API and renders returned headings', async () => {
    mockRequestOutline.mockResolvedValue({
      title: 'Cash Assistance Brief',
      headings: [
        { title: 'Background', level: 1 },
        { title: 'Food security', level: 2 },
      ],
    });
    render(<BriefTab dataSource="wfp" />);
    fireEvent.click(screen.getByText('✦ Generate outline'));

    await waitFor(() => {
      expect(screen.getByText('Cash Assistance Brief')).toBeInTheDocument();
    });
    expect(mockRequestOutline).toHaveBeenCalledTimes(1);
    expect(mockRequestOutline.mock.calls[0][0]).toMatchObject({ dataSource: 'wfp' });
    expect(screen.getByDisplayValue('Background')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Food security')).toBeInTheDocument();
  });
});
