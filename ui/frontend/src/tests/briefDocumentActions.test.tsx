import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { BriefDocumentActions } from '../components/brief/BriefDocumentActions';
import { IconShare } from '../components/brief/BriefIcons';

test('expanded actions are direct buttons and compact actions use the More menu', () => {
  const share = jest.fn();
  const actions = [{ label: 'Share', icon: IconShare, onSelect: share }];
  const { rerender } = render(<BriefDocumentActions actions={actions} compact={false} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share' }));
  expect(share).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole('button', { name: 'More actions' })).toBeNull();
  rerender(<BriefDocumentActions actions={actions} compact />);
  expect(screen.queryByRole('button', { name: 'Share' })).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'More actions' }));
  fireEvent.click(screen.getByRole('button', { name: 'Share' }));
  expect(share).toHaveBeenCalledTimes(2);
});

test('disabled desktop actions remain disabled and empty actions render no controls', () => {
  const share = jest.fn();
  const { rerender } = render(<BriefDocumentActions compact={false} actions={[{ label: 'Share', icon: IconShare, onSelect: share, disabled: true }]} />);
  fireEvent.click(screen.getByRole('button', { name: 'Share' }));
  expect(share).not.toHaveBeenCalled();
  rerender(<BriefDocumentActions compact={false} actions={[]} />);
  expect(screen.queryByRole('button')).toBeNull();
});

test('document output actions occupy the trailing group while Share stays before them', () => {
  const onSelect = jest.fn();
  render(<BriefDocumentActions compact={false} actions={[
    { label: 'Share', icon: IconShare, onSelect },
    { label: 'Export', icon: IconShare, onSelect, align: 'end' },
  ]} />);
  const group = screen.getByRole('group', { name: 'Document output and history' });
  expect(within(group).getByRole('button', { name: 'Export' })).toBeVisible();
  expect(within(group).queryByRole('button', { name: 'Share' })).toBeNull();
});
