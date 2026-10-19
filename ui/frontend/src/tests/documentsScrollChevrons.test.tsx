import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';

import { SCROLL_STEP_FRACTION, ScrollChevrons } from '../components/documents/ScrollChevrons';

/** A scroll container as jsdom cannot lay one out: explicit geometry, live scrollLeft. */
const makeContainer = ({ scrollWidth, clientWidth, scrollLeft = 0 }: {
  scrollWidth: number;
  clientWidth: number;
  scrollLeft?: number;
}) => {
  const el = document.createElement('div');
  let left = scrollLeft;
  Object.defineProperty(el, 'scrollWidth', { configurable: true, get: () => scrollWidth });
  Object.defineProperty(el, 'clientWidth', { configurable: true, get: () => clientWidth });
  Object.defineProperty(el, 'scrollLeft', {
    configurable: true,
    get: () => left,
    set: (value: number) => {
      left = Math.max(0, Math.min(value, scrollWidth - clientWidth));
    },
  });
  return el;
};

const left = () => screen.queryByLabelText('Scroll table left');
const right = () => screen.queryByLabelText('Scroll table right');

describe('ScrollChevrons', () => {
  test('renders nothing when the table does not overflow', () => {
    render(<ScrollChevrons container={makeContainer({ scrollWidth: 800, clientWidth: 800 })} />);
    expect(left()).toBeNull();
    expect(right()).toBeNull();
  });

  test('renders nothing without a container', () => {
    render(<ScrollChevrons container={null} />);
    expect(right()).toBeNull();
  });

  test('on load only the right chevron shows; the left appears once scrolled', () => {
    const el = makeContainer({ scrollWidth: 2180, clientWidth: 1000 });
    render(<ScrollChevrons container={el} />);
    expect(right()).toBeInTheDocument();
    expect(left()).toBeNull();

    act(() => {
      el.scrollLeft = 300;
      el.dispatchEvent(new Event('scroll'));
    });
    expect(left()).toBeInTheDocument();
    expect(right()).toBeInTheDocument();
  });

  test('at the far right only the left chevron remains', () => {
    const el = makeContainer({ scrollWidth: 2180, clientWidth: 1000, scrollLeft: 1180 });
    render(<ScrollChevrons container={el} />);
    expect(left()).toBeInTheDocument();
    expect(right()).toBeNull();
  });

  test('clicking scrolls by a step of the visible width and updates the chevrons', () => {
    const el = makeContainer({ scrollWidth: 2180, clientWidth: 1000 });
    render(<ScrollChevrons container={el} />);

    fireEvent.click(right()!);
    expect(el.scrollLeft).toBe(Math.round(1000 * SCROLL_STEP_FRACTION));
    expect(left()).toBeInTheDocument();

    fireEvent.click(left()!);
    expect(el.scrollLeft).toBe(0);
    expect(left()).toBeNull();
    expect(right()).toBeInTheDocument();
  });

  test('chevrons are buttons, not links or divs, and carry an accessible name', () => {
    const el = makeContainer({ scrollWidth: 2180, clientWidth: 1000, scrollLeft: 100 });
    render(<ScrollChevrons container={el} />);
    for (const btn of [left()!, right()!]) {
      expect(btn.tagName).toBe('BUTTON');
      expect(btn).toHaveAttribute('type', 'button');
    }
  });
});
