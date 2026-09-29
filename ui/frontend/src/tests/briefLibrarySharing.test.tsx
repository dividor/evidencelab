import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BriefCentral } from '../components/brief/BriefCentral';
import { LibraryShareModal } from '../components/brief/BriefShareDialog';
import { BriefListItem, BriefTemplate, VoiceProfile } from '../components/brief/briefTypes';
import { CentralTab, UseBriefCentralReturn } from '../components/brief/useBriefCentral';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
}));

const mockListShares = jest.fn();
const mockAddShare = jest.fn();
const mockRemoveShare = jest.fn();
const mockSearch = jest.fn();
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  listLibraryShares: (...args: unknown[]) => mockListShares(...args),
  addLibraryShare: (...args: unknown[]) => mockAddShare(...args),
  removeLibraryShare: (...args: unknown[]) => mockRemoveShare(...args),
  searchShareTargets: (...args: unknown[]) => mockSearch(...args),
  recordTemplateUse: jest.fn(async () => ({})),
  getBrief: jest.fn(),
  addBriefShare: jest.fn(),
  removeBriefShare: jest.fn(),
}));

const NOW = '2026-09-29T10:00:00Z';
const PRIYA = { id: 's-1', name: 'Priya Raman', kind: 'priya@example.org', is_group: false };
const TEAM = { id: 's-2', name: 'OEV team', kind: 'Group · 4 members', is_group: true };

const template = (id: string, name: string, extra: Partial<BriefTemplate> = {}): BriefTemplate => ({
  id,
  name,
  description: null,
  headings: [{ title: 'Findings', sub: false, prompt: 'Lead with outcomes' }],
  with_text: false,
  prompt: null,
  voice_profile_id: null,
  target_words: null,
  use_count: 0,
  owner_name: null,
  can_edit: true,
  share_count: 0,
  created_at: NOW,
  updated_at: NOW,
  ...extra,
});

const voice = (id: string, name: string, extra: Partial<VoiceProfile> = {}): VoiceProfile => ({
  id,
  name,
  description: null,
  instructions: 'Plain English.',
  owner_name: null,
  can_edit: true,
  share_count: 0,
  created_at: NOW,
  updated_at: NOW,
  ...extra,
});

beforeEach(() => {
  mockListShares.mockResolvedValue([PRIYA]);
  mockAddShare.mockResolvedValue([PRIYA, TEAM]);
  mockRemoveShare.mockResolvedValue(undefined);
  mockSearch.mockResolvedValue({ users: [], groups: [] });
});

describe('sharing a template or voice', () => {
  test('lists, adds and removes people and groups, reporting the new count', async () => {
    const onChanged = jest.fn();
    render(
      <LibraryShareModal kind="template" itemId="t-1" itemName="Board memo" onChanged={onChanged} onClose={jest.fn()} />,
    );

    expect(await screen.findByText('Priya Raman')).toBeInTheDocument();
    expect(mockListShares).toHaveBeenCalledWith('template', 't-1');
    expect(screen.getByText('Share “Board memo”')).toBeInTheDocument();
    expect(screen.getByText('Can use')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('Search people or groups'), { target: { value: 'OEV team' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('OEV team')).toBeInTheDocument();
    expect(mockAddShare).toHaveBeenCalledWith('template', 't-1', 'OEV team');
    expect(onChanged).toHaveBeenLastCalledWith(2);

    fireEvent.click(screen.getByRole('button', { name: 'Remove access for Priya Raman' }));
    await waitFor(() => expect(screen.queryByText('Priya Raman')).toBeNull());
    expect(mockRemoveShare).toHaveBeenCalledWith('template', 't-1', 's-1');
    expect(onChanged).toHaveBeenLastCalledWith(1);
  });

  test('a voice profile shares through its own endpoints', async () => {
    render(<LibraryShareModal kind="voice" itemId="v-1" itemName="Donor memo" onClose={jest.fn()} />);
    await screen.findByText('Priya Raman');
    expect(mockListShares).toHaveBeenCalledWith('voice', 'v-1');
    expect(screen.getByText(/write with this voice & tone profile/)).toBeInTheDocument();
  });

  test('picking a group from the suggestions shares with it straight away', async () => {
    mockSearch.mockResolvedValue({
      users: [{ email: 'oev.lead@example.org', name: 'OEV Lead' }],
      groups: [{ name: 'OEV' }, { name: 'OEV_test' }],
    });
    const onChanged = jest.fn();
    render(
      <LibraryShareModal kind="template" itemId="t-1" itemName="Board memo" onChanged={onChanged} onClose={jest.fn()} />,
    );
    await screen.findByText('Priya Raman');
    fireEvent.change(screen.getByPlaceholderText('Search people or groups'), { target: { value: 'OEV' } });

    const group = await screen.findByRole('option', { name: /OEV_test.*Group/ });
    fireEvent.click(group);

    await waitFor(() => expect(mockAddShare).toHaveBeenCalledWith('template', 't-1', 'OEV_test'));
    expect(mockSearch).toHaveBeenCalledWith('OEV');
    expect(await screen.findByText('OEV team')).toBeInTheDocument();
    expect(screen.queryByRole('listbox')).toBeNull();
    expect(screen.getByPlaceholderText('Search people or groups')).toHaveValue('');
    expect(onChanged).toHaveBeenLastCalledWith(2);
  });

  test('arrow keys pick a suggestion and Enter shares with it', async () => {
    mockSearch.mockResolvedValue({ users: [], groups: [{ name: 'OEV' }, { name: 'OEV_test' }] });
    render(<LibraryShareModal kind="voice" itemId="v-1" itemName="Donor memo" onClose={jest.fn()} />);
    await screen.findByText('Priya Raman');
    const box = screen.getByPlaceholderText('Search people or groups');
    fireEvent.change(box, { target: { value: 'OE' } });
    await screen.findByRole('option', { name: /OEV_test/ });

    fireEvent.keyDown(box, { key: 'ArrowDown' });
    fireEvent.keyDown(box, { key: 'ArrowDown' });
    expect(screen.getByRole('option', { name: /OEV_test/ })).toHaveAttribute('aria-selected', 'true');
    fireEvent.keyDown(box, { key: 'Enter' });

    await waitFor(() => expect(mockAddShare).toHaveBeenCalledWith('voice', 'v-1', 'OEV_test'));
  });

  test('Enter with nothing picked shares with what was typed', async () => {
    render(<LibraryShareModal kind="voice" itemId="v-1" itemName="Donor memo" onClose={jest.fn()} />);
    await screen.findByText('Priya Raman');
    const box = screen.getByPlaceholderText('Search people or groups');
    fireEvent.change(box, { target: { value: 'someone@example.org' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(mockAddShare).toHaveBeenCalledWith('voice', 'v-1', 'someone@example.org'));
  });

  test('an error from the server is shown, not swallowed', async () => {
    mockAddShare.mockRejectedValue(new Error('No user with that email address'));
    render(<LibraryShareModal kind="voice" itemId="v-1" itemName="Donor memo" onClose={jest.fn()} />);
    await screen.findByText('Priya Raman');
    fireEvent.change(screen.getByPlaceholderText('Search people or groups'), { target: { value: 'x@y.z' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));
    expect(await screen.findByText('No user with that email address')).toBeInTheDocument();
    expect(screen.getByPlaceholderText('Search people or groups')).toHaveValue('x@y.z');
  });
});

const fakeCentral = (tab: CentralTab, overrides: Partial<UseBriefCentralReturn> = {}): UseBriefCentralReturn =>
  ({
    tab,
    setTab: jest.fn(),
    myBriefs: [],
    sharedBriefs: [],
    templates: [
      template('t-mine', 'My template', { share_count: 2 }),
      template('t-theirs', 'Their template', { can_edit: false, owner_name: 'Priya' }),
    ],
    voices: [
      voice('v-mine', 'My voice'),
      voice('v-theirs', 'Their voice', { can_edit: false, owner_name: 'Priya' }),
    ],
    loading: false,
    error: null,
    setError: jest.fn(),
    refresh: jest.fn(),
    removeBrief: jest.fn().mockResolvedValue(undefined),
    saveTemplate: jest.fn(),
    copyTemplate: jest.fn().mockResolvedValue(template('t-copy', 'Copy of Their template')),
    removeTemplate: jest.fn().mockResolvedValue(undefined),
    setTemplateShareCount: jest.fn(),
    saveVoice: jest.fn(),
    copyVoice: jest.fn().mockResolvedValue(voice('v-copy', 'Copy of Their voice')),
    removeVoice: jest.fn().mockResolvedValue(undefined),
    setVoiceShareCount: jest.fn(),
    refreshVoices: jest.fn().mockResolvedValue(undefined),
    voiceById: () => null,
    ...overrides,
  }) as unknown as UseBriefCentralReturn;

const card = (title: string): HTMLElement =>
  screen.getByText(title).closest('.bc-card') as HTMLElement;

describe('Brief Central library cards', () => {
  test('an owned template can be used, copied, edited, shared and deleted', () => {
    render(<BriefCentral central={fakeCentral('templates')} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    const mine = within(card('My template'));
    for (const name of ['Use Template', 'Edit', 'Share', 'Copy', 'Delete']) {
      expect(mine.getByRole('button', { name })).toBeInTheDocument();
    }
    expect(mine.queryByRole('button', { name: '×' })).toBeNull();
    expect(mine.getByText('Shared with 2 · 1 heading · 1 prompt')).toBeInTheDocument();
    expect(mine.getByRole('button', { name: 'Use Template' })).toHaveClass('brief-btn-primary');
    expect(mine.getByText('prompt')).toBeInTheDocument();
  });

  test('a shared template names its owner and can only be used or copied', () => {
    const central = fakeCentral('templates');
    render(<BriefCentral central={central} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    const theirs = within(card('Their template'));
    expect(theirs.getByText('Shared by Priya · 1 heading · 1 prompt')).toBeInTheDocument();
    expect(theirs.getByRole('button', { name: 'Use Template' })).toBeInTheDocument();
    expect(theirs.queryByRole('button', { name: /Edit/ })).toBeNull();
    expect(theirs.queryByRole('button', { name: /Share/ })).toBeNull();
    expect(theirs.queryByRole('button', { name: /Delete/ })).toBeNull();

    fireEvent.click(theirs.getByRole('button', { name: /Copy/ }));
    expect(central.copyTemplate).toHaveBeenCalledWith('t-theirs');
  });

  test('Edit opens the editor on the template, and Share opens its Share dialog', async () => {
    render(<BriefCentral central={fakeCentral('templates')} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    fireEvent.click(within(card('My template')).getByRole('button', { name: /Edit/ }));
    expect(screen.getByText('Edit template')).toBeInTheDocument();
    expect(screen.getByDisplayValue('My template')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    fireEvent.click(within(card('My template')).getByRole('button', { name: /Share/ }));
    expect(await screen.findByText('Share “My template”')).toBeInTheDocument();
    expect(mockListShares).toHaveBeenCalledWith('template', 't-mine');
  });

  test('a shared voice can only be copied; an owned one can also be edited, shared and deleted', () => {
    const central = fakeCentral('voices');
    render(<BriefCentral central={central} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    const theirs = within(card('Their voice'));
    expect(theirs.getByText(/by Priya/)).toBeInTheDocument();
    expect(theirs.queryByRole('button', { name: /Edit/ })).toBeNull();
    fireEvent.click(theirs.getByRole('button', { name: /Copy/ }));
    expect(central.copyVoice).toHaveBeenCalledWith('v-theirs');

    const mine = within(card('My voice'));
    expect(mine.getByRole('button', { name: /Share/ })).toBeInTheDocument();
    expect(mine.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(mine.queryByRole('button', { name: 'Use Template' })).toBeNull();
  });
});

const briefItem = (id: string, title: string, extra: Partial<BriefListItem> = {}): BriefListItem => ({
  id,
  title,
  query: null,
  data_source: 'wfp',
  voice_profile_id: null,
  section_count: 3,
  source_count: 12,
  owner_name: null,
  share_count: 0,
  created_at: NOW,
  updated_at: NOW,
  ...extra,
});

describe('Brief Central saved-brief cards', () => {
  test('an owned brief opens from a filled Open Brief, with Share and Delete beneath', () => {
    const onOpen = jest.fn();
    const central = fakeCentral('mine', {
      myBriefs: [briefItem('b-1', 'School feeding', { share_count: 2 })],
      voiceById: () => voice('v-mine', 'Donor memo'),
    });
    render(<BriefCentral central={central} onOpenBrief={onOpen} onCreateBrief={jest.fn()} />);
    const mine = within(card('School feeding'));

    expect(mine.getByRole('button', { name: 'Open Brief' })).toHaveClass('brief-btn-primary');
    expect(mine.getByRole('button', { name: 'Share' })).toBeInTheDocument();
    expect(mine.getByRole('button', { name: 'Delete' })).toBeInTheDocument();
    expect(mine.queryByRole('button', { name: '×' })).toBeNull();
    expect(mine.getByText(/^Shared with 2 · Donor memo · /)).toBeInTheDocument();

    fireEvent.click(mine.getByRole('button', { name: 'Open Brief' }));
    expect(onOpen).toHaveBeenCalledWith('b-1');
    fireEvent.click(mine.getByRole('button', { name: 'Delete' }));
    expect(central.removeBrief).toHaveBeenCalledWith('b-1');
  });

  test('a brief shared with me names its owner and can only be opened', () => {
    const central = fakeCentral('shared', {
      sharedBriefs: [briefItem('b-2', 'Cash transfers', { owner_name: 'Priya' })],
    });
    render(<BriefCentral central={central} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    const theirs = within(card('Cash transfers'));
    expect(theirs.getByText(/^Shared by Priya · /)).toBeInTheDocument();
    expect(theirs.getByRole('button', { name: 'Open Brief' })).toBeInTheDocument();
    expect(theirs.queryByRole('button', { name: 'Share' })).toBeNull();
    expect(theirs.queryByRole('button', { name: 'Delete' })).toBeNull();
  });
});

test('sharing a template reloads the voices, whose shares it may have changed', async () => {
  const central = fakeCentral('templates');
  render(<BriefCentral central={central} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
  fireEvent.click(within(card('My template')).getByRole('button', { name: /Share/ }));
  expect(await screen.findByText(/voice & tone profiles it uses that you own are shared/)).toBeInTheDocument();
  fireEvent.change(screen.getByPlaceholderText('Search people or groups'), { target: { value: 'OEV team' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add' }));
  await waitFor(() => expect(central.setTemplateShareCount).toHaveBeenCalledWith('t-mine', 2));
  expect(central.refreshVoices).toHaveBeenCalled();
});
