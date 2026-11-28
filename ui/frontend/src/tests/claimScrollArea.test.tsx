import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { ClaimScrollArea } from '../components/brief/ClaimScrollArea';

const AREA = 'Claim assessment and sources';

test('See more scrolls the actual viewport and disappears at the bottom', () => {
  render(<ClaimScrollArea><p>A long source excerpt</p></ClaimScrollArea>);
  const viewport = screen.getByRole('region', { name: AREA });
  Object.defineProperties(viewport, {
    clientHeight: { configurable: true, value: 200 },
    scrollHeight: { configurable: true, value: 700 },
    scrollTop: { configurable: true, value: 0, writable: true },
  });
  viewport.scrollBy = jest.fn();
  fireEvent.scroll(viewport);
  fireEvent.click(screen.getByRole('button', { name: 'See more' }));
  expect(viewport.scrollBy).toHaveBeenCalledWith({ top: 150, behavior: 'smooth' });
  viewport.scrollTop = 500;
  fireEvent.scroll(viewport);
  expect(screen.queryByRole('button', { name: 'See more' })).toBeNull();
});

test('short content needs no scrolling control', () => {
  render(<ClaimScrollArea><p>A short claim</p></ClaimScrollArea>);
  expect(screen.getByRole('region', { name: AREA })).toHaveAttribute('tabindex', '0');
  expect(screen.queryByRole('button', { name: 'See more' })).toBeNull();
});
