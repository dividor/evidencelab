import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { NavTabs } from './NavTabs';

describe('NavTabs Monitor dropdown', () => {
  afterEach(() => {
    jest.useRealTimers();
  });

  it('still selects an item when the click lands long after the trigger lost focus', () => {
    jest.useFakeTimers();
    const onTabChange = jest.fn();
    render(<NavTabs activeTab="search" onTabChange={onTabChange} />);
    const trigger = screen.getByText('Monitor');
    fireEvent.click(trigger);
    const item = screen.getByText('Pipeline');
    // A real click moves focus off the trigger on mouse-down; the mouse-up
    // (and so the click) can arrive much later on a slow click or a remote
    // desktop. The item must still be there when it does.
    fireEvent.mouseDown(item);
    fireEvent.focusOut(trigger);
    act(() => {
      jest.advanceTimersByTime(1000);
    });
    fireEvent.click(item);
    expect(onTabChange).toHaveBeenCalledWith('pipeline');
    expect(screen.queryByText('Pipeline')).not.toBeInTheDocument();
  });

  it('closes when the user presses outside the dropdown', () => {
    render(<NavTabs activeTab="search" onTabChange={jest.fn()} />);
    fireEvent.click(screen.getByText('Monitor'));
    expect(screen.getByText('Stats')).toBeInTheDocument();
    fireEvent.mouseDown(document.body);
    expect(screen.queryByText('Stats')).not.toBeInTheDocument();
  });
});
