import React from 'react';
import { render, screen, within } from '@testing-library/react';

import { NavTabs } from '../components/layout/NavTabs';
import { TAB_TOOLTIPS } from '../components/layout/tabConfig';

describe('NavTabs tooltips', () => {
  it('renders a tooltip with the correct copy on every main tab', () => {
    render(<NavTabs activeTab="search" onTabChange={() => {}} />);

    const tooltips = screen.getAllByRole('tooltip');
    const texts = tooltips.map((el) => el.textContent);

    expect(texts).toContain(TAB_TOOLTIPS.search);
    expect(texts).toContain(TAB_TOOLTIPS.assistant);
    expect(texts).toContain(TAB_TOOLTIPS.brief);
    expect(texts).toContain(TAB_TOOLTIPS.heatmap);
  });

  it('nests each tooltip inside its tab button so it anchors to that tab', () => {
    render(<NavTabs activeTab="search" onTabChange={() => {}} />);

    const searchTab = screen.getByRole('button', { name: /Search/ });
    expect(
      within(searchTab).getByText(TAB_TOOLTIPS.search),
    ).toBeInTheDocument();
  });

  it('omits tooltips for tabs a group has disabled', () => {
    render(
      <NavTabs
        activeTab="search"
        onTabChange={() => {}}
        tabs={{
          search: { enabled: true, label: 'Search' },
          assistant: { enabled: false, label: 'Chat' },
          brief: { enabled: true, label: 'Brief' },
          heatmap: { enabled: true, label: 'Map' },
        }}
      />,
    );

    const texts = screen
      .getAllByRole('tooltip')
      .map((el) => el.textContent);
    expect(texts).toContain(TAB_TOOLTIPS.search);
    expect(texts).not.toContain(TAB_TOOLTIPS.assistant);
  });
});
