import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';

import { TopBar } from './TopBar';

// Isolate the brand: stub child components that pull in auth/model context.
// jest.mock is hoisted above the imports by the transform, so the mocks
// still apply to the TopBar import above.
jest.mock('./ModelComboPanel', () => ({ ModelComboPanel: () => null }));
jest.mock('../auth/UserMenu', () => () => null);

const noop = () => {};

const baseProps: any = {
  selectedDomain: 'WFP',
  availableDomains: ['WFP'],
  datasetTotals: { WFP: 333 },
  selectedModelCombo: 'default',
  availableModelCombos: ['default'],
  modelCombos: {},
  domainDropdownOpen: false,
  modelDropdownOpen: false,
  helpDropdownOpen: false,
  showDomainTooltip: false,
  onToggleDomainDropdown: noop,
  onToggleModelDropdown: noop,
  onDomainMouseEnter: noop,
  onDomainMouseLeave: noop,
  onCloseDomainDropdown: noop,
  onCloseModelDropdown: noop,
  onSelectDomain: noop,
  onSelectModelCombo: noop,
  onToggleHelpDropdown: noop,
  onCloseHelpDropdown: noop,
  onAboutClick: noop,
  onTechClick: noop,
  onDataClick: noop,
  onDocsClick: noop,
};

describe('TopBar brand link', () => {
  it('renders the logo and title as a link to the home page', () => {
    render(<TopBar {...baseProps} />);
    const link = screen.getByRole('link', { name: /go to home page/i });
    expect(link.tagName).toBe('A');
    expect(link.getAttribute('href')).toBe('/');
    // logo + title live inside the link
    screen.getByAltText('Evidence Lab Logo');
    screen.getByText('Evidence Lab');
  });

  it('navigates home via SPA history on a plain click (no full reload)', () => {
    const pushState = jest.spyOn(window.history, 'pushState');
    const dispatch = jest.spyOn(window, 'dispatchEvent');
    render(<TopBar {...baseProps} />);

    const link = screen.getByRole('link', { name: /go to home page/i });
    const clickEvent = fireEvent.click(link);

    expect(pushState).toHaveBeenCalledWith(null, '', '/');
    expect(
      dispatch.mock.calls.some(([evt]) => (evt as Event).type === 'popstate')
    ).toBe(true);
    // default navigation is prevented so the SPA does not do a full reload
    expect(clickEvent).toBe(false);

    pushState.mockRestore();
    dispatch.mockRestore();
  });

  it('does not hijack modified clicks (e.g. open-in-new-tab)', () => {
    const pushState = jest.spyOn(window.history, 'pushState');
    render(<TopBar {...baseProps} />);

    const link = screen.getByRole('link', { name: /go to home page/i });
    fireEvent.click(link, { metaKey: true });

    expect(pushState).not.toHaveBeenCalled();
    pushState.mockRestore();
  });
});

describe('TopBar dropdown dismissal', () => {
  afterEach(() => {
    jest.useRealTimers();
  });

  it('closes the open Info dropdown on mouse-down outside it, but not inside it', () => {
    const onCloseHelpDropdown = jest.fn();
    render(<TopBar {...baseProps} helpDropdownOpen onCloseHelpDropdown={onCloseHelpDropdown} />);
    fireEvent.mouseDown(screen.getByText('About'));
    expect(onCloseHelpDropdown).not.toHaveBeenCalled();
    fireEvent.mouseDown(document.body);
    expect(onCloseHelpDropdown).toHaveBeenCalledTimes(1);
  });

  it('keeps an Info item clickable long after the trigger lost focus', () => {
    jest.useFakeTimers();
    const onAboutClick = jest.fn();
    render(<TopBar {...baseProps} helpDropdownOpen onAboutClick={onAboutClick} />);
    const item = screen.getByText('About');
    fireEvent.mouseDown(item);
    fireEvent.focusOut(screen.getByText('Info'));
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    fireEvent.click(item);
    expect(onAboutClick).toHaveBeenCalledTimes(1);
  });
});
