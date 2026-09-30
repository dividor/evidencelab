import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BriefCentral } from '../components/brief/BriefCentral';
import { filterBriefs } from '../components/brief/briefSearch';
import { BriefListItem, RemoteBrief } from '../components/brief/briefTypes';
import { CentralTab, UseBriefCentralReturn } from '../components/brief/useBriefCentral';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: true }));
jest.mock('../components/brief/briefCentralApi', () => ({
  __esModule: true,
  recordTemplateUse: jest.fn(async () => ({})),
  searchShareTargets: jest.fn(async () => ({ users: [], groups: [] })),
}));

const NOW = '2026-09-30T10:00:00Z';
const ALL_TAB = 'All Briefs (Admin)';
const PRIYA = 'Priya Raman';
const PRIYA_EMAIL = 'priya@example.org';
const KENYA = 'School feeding in Kenya';
const CASH = 'Cash transfers review';
const NUTRITION = 'Nutrition in schools';
const SEARCH = 'Search all briefs by name or user';

const item = (id: string, title: string, owner: string, email: string): BriefListItem => ({
  id,
  title,
  query: null,
  data_source: 'wfp',
  voice_profile_id: null,
  section_count: 3,
  source_count: 12,
  owner_name: owner,
  owner_email: email,
  share_count: 0,
  created_at: NOW,
  updated_at: NOW,
});

const ALL = [
  item('b1', KENYA, PRIYA, PRIYA_EMAIL),
  item('b2', CASH, 'Tom Okello', 'tom@example.org'),
  item('b3', NUTRITION, PRIYA, PRIYA_EMAIL),
];

describe('filterBriefs', () => {
  test('an empty search shows everything', () => {
    expect(filterBriefs(ALL, '  ')).toEqual(ALL);
  });

  test('matches the brief name, ignoring case', () => {
    expect(filterBriefs(ALL, 'KENYA').map((b) => b.id)).toEqual(['b1']);
  });

  test("matches the owner's name or email", () => {
    expect(filterBriefs(ALL, 'priya').map((b) => b.id)).toEqual(['b1', 'b3']);
    expect(filterBriefs(ALL, 'tom@example').map((b) => b.id)).toEqual(['b2']);
  });

  test('every word must match, across name and owner', () => {
    expect(filterBriefs(ALL, 'priya schools').map((b) => b.id)).toEqual(['b3']);
    expect(filterBriefs(ALL, 'tom kenya')).toEqual([]);
  });
});

const fakeCentral = (tab: CentralTab, overrides: Partial<UseBriefCentralReturn> = {}): UseBriefCentralReturn =>
  ({
    tab,
    setTab: jest.fn(),
    myBriefs: [],
    sharedBriefs: [],
    templates: [],
    voices: [],
    allBriefs: ALL,
    isAdmin: true,
    loading: false,
    error: null,
    setError: jest.fn(),
    refresh: jest.fn(),
    removeBrief: jest.fn().mockResolvedValue(undefined),
    copyBrief: jest.fn().mockResolvedValue({ id: 'copy-1', title: 'Cash transfers review (copy)' } as RemoteBrief),
    saveTemplate: jest.fn(),
    copyTemplate: jest.fn(),
    removeTemplate: jest.fn(),
    setTemplateShareCount: jest.fn(),
    saveVoice: jest.fn(),
    copyVoice: jest.fn(),
    removeVoice: jest.fn(),
    setVoiceShareCount: jest.fn(),
    refreshVoices: jest.fn(),
    voiceById: () => null,
    ...overrides,
  }) as unknown as UseBriefCentralReturn;

const card = (title: string): HTMLElement => screen.getByText(title).closest('.bc-card') as HTMLElement;

describe('the All Briefs (Admin) tab', () => {
  test('only administrators see the tab', () => {
    const { rerender } = render(
      <BriefCentral central={fakeCentral('mine', { isAdmin: false })} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />,
    );
    expect(screen.queryByRole('tab', { name: ALL_TAB })).toBeNull();
    rerender(<BriefCentral central={fakeCentral('mine')} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    expect(screen.getByRole('tab', { name: ALL_TAB })).toBeInTheDocument();
  });

  test('lists every brief with its owner', () => {
    render(<BriefCentral central={fakeCentral('all')} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    expect(within(card(KENYA)).getByText(/^Owner: Priya Raman \(priya@example\.org\) · /)).toBeInTheDocument();
    expect(within(card(CASH)).getByText(/^Owner: Tom Okello \(tom@example\.org\) · /)).toBeInTheDocument();
    expect(screen.getByText('3 of 3 briefs')).toBeInTheDocument();
  });

  test('the search box filters the cards by brief name or user', () => {
    render(<BriefCentral central={fakeCentral('all')} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    fireEvent.change(screen.getByLabelText(SEARCH), { target: { value: 'tom' } });
    expect(screen.getByText(CASH)).toBeInTheDocument();
    expect(screen.queryByText(KENYA)).toBeNull();
    expect(screen.getByText('1 of 3 briefs')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(SEARCH), { target: { value: 'nothing like this' } });
    expect(screen.getByText('No briefs match your search.')).toBeInTheDocument();
  });

  test('Open Brief opens that brief', () => {
    const onOpen = jest.fn();
    render(<BriefCentral central={fakeCentral('all')} onOpenBrief={onOpen} onCreateBrief={jest.fn()} />);
    fireEvent.click(within(card(NUTRITION)).getByRole('button', { name: 'Open Brief' }));
    expect(onOpen).toHaveBeenCalledWith('b3');
  });

  test('Copy puts a copy in the admin’s own Saved Briefs and says so', async () => {
    const central = fakeCentral('all');
    render(<BriefCentral central={central} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    fireEvent.click(within(card(CASH)).getByRole('button', { name: /Copy/ }));
    expect(central.copyBrief).toHaveBeenCalledWith('b2');
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Copied to your Saved Briefs as “Cash transfers review (copy)”.',
    );
  });

  test('a failed copy is reported', async () => {
    const central = fakeCentral('all', { copyBrief: jest.fn().mockRejectedValue(new Error('Forbidden')) });
    render(<BriefCentral central={central} onOpenBrief={jest.fn()} onCreateBrief={jest.fn()} />);
    fireEvent.click(within(card(CASH)).getByRole('button', { name: /Copy/ }));
    await waitFor(() => expect(central.setError).toHaveBeenCalledWith('Could not copy: Forbidden'));
  });
});
