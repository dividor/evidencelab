import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { BriefDocumentActions } from '../components/brief/BriefDocumentActions';
import { IconShare } from '../components/brief/BriefIcons';

const initialWidth = window.innerWidth;
afterEach(() => { window.innerWidth = initialWidth; });

test('desktop exposes actions directly and resizing groups them into More Actions', () => {
  window.innerWidth = 1440;
  const share = jest.fn();
  render(<BriefDocumentActions actions={[{ label: 'Share', icon: IconShare, onSelect: share }]} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share' }));
  expect(share).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'More actions' })).toBeNull();
  act(() => { window.innerWidth = 390; window.dispatchEvent(new Event('resize')); });
  expect(screen.queryByRole('button', { name: 'Share' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
  fireEvent.click(screen.getByRole('button', { name: 'Share' }));
  expect(share).toHaveBeenCalledTimes(2);
});

test('disabled desktop actions remain disabled and empty actions render no controls', () => {
  window.innerWidth = 1440;
  const share = jest.fn();
  const { rerender } = render(<BriefDocumentActions actions={[{ label: 'Share', icon: IconShare, onSelect: share, disabled: true }]} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share' }));
  expect(share).not.toHaveBeenCalled();
  rerender(<BriefDocumentActions actions={[]} />);
  expect(screen.queryByRole('button')).toBeNull();
});

test('document output actions occupy the trailing group while Share stays before them', () => {
  window.innerWidth = 1440;
  const onSelect = jest.fn();
  render(<BriefDocumentActions actions={[
    { label: 'Share', icon: IconShare, onSelect },
    { label: 'Export', icon: IconShare, onSelect, align: 'end' },
  ]} />);
  const group = screen.getByRole('group', { name: 'Document output and history' });
  expect(within(group).getByRole('button', { name: 'Export' })).toBeVisible();
  expect(within(group).queryByRole('button', { name: 'Share' })).toBeNull();
});
