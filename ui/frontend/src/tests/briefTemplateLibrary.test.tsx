import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { BriefNewModal, NewBriefSubmit, numberHeadings } from '../components/brief/BriefCentralModals';
import {
  BriefTemplateModal,
  TemplateDraft,
  draftFromTemplate,
  draftHeading,
  draftToPayload,
  emptyTemplateDraft,
} from '../components/brief/BriefTemplateModal';
import {
  BriefVoiceSelect,
  UNAVAILABLE_VOICE_LABEL,
  briefDefaultSuffix,
  voiceHint,
} from '../components/brief/BriefVoiceSelect';
import { BriefTemplate, VoiceProfile } from '../components/brief/briefTypes';
import { sectionFromTemplateHeading } from '../components/brief/useBrief';

jest.mock('../config', () => ({
  __esModule: true,
  default: '/api',
  API_KEY: undefined,
  USER_MODULE: true,
}));

const NOW = '2026-09-29T10:00:00Z';

const voice = (id: string, name: string, extra: Partial<VoiceProfile> = {}): VoiceProfile => ({
  id,
  name,
  description: null,
  instructions: `${name} instructions`,
  owner_name: null,
  can_edit: true,
  share_count: 0,
  created_at: NOW,
  updated_at: NOW,
  ...extra,
});

const MINE = voice('v-mine', 'Donor memo');
const SHARED = voice('v-shared', 'Field summary', { can_edit: false, owner_name: 'Priya' });
const VOICES = [MINE, SHARED];

const template = (extra: Partial<BriefTemplate> = {}): BriefTemplate => ({
  id: 't-1',
  name: 'Evaluation synthesis',
  description: null,
  headings: [
    { title: 'Context', sub: false },
    { title: 'Findings', sub: false, prompt: 'Lead with outcomes', voice_profile_id: 'v-mine', target_words: 150 },
  ],
  with_text: false,
  prompt: 'Focus on East Africa',
  voice_profile_id: 'v-shared',
  target_words: 700,
  use_count: 0,
  owner_name: null,
  can_edit: true,
  share_count: 0,
  created_at: NOW,
  updated_at: NOW,
  ...extra,
});

const fromBriefDraft = (extra: Partial<TemplateDraft> = {}): TemplateDraft => ({
  ...emptyTemplateDraft(),
  fromBrief: true,
  name: 'From a brief',
  headings: [
    draftHeading({ title: 'Summary', sub: false, text: 'Draft text', prompt: '  Three bullets  ', target_words: 150 }),
    draftHeading({ title: '   ', sub: false }),
  ],
  prompt: 'Whole brief',
  voiceId: 'v-mine',
  targetWords: 350,
  ...extra,
});

describe('template payloads', () => {
  test('keeps prompts, voices and lengths, trimmed, and drops untitled headings', () => {
    const payload = draftToPayload(fromBriefDraft());
    expect(payload.headings).toEqual([
      {
        title: 'Summary',
        sub: false,
        text: null,
        prompt: 'Three bullets',
        voice_profile_id: null,
        target_words: 150,
      },
    ]);
    expect([payload.prompt, payload.voiceProfileId, payload.targetWords]).toEqual(['Whole brief', 'v-mine', 350]);
  });

  test('saving from a brief without prompts and settings leaves them all out', () => {
    const payload = draftToPayload(fromBriefDraft({ withSettings: false, withText: true }));
    expect(payload.headings[0]).toMatchObject({ text: 'Draft text', prompt: null, target_words: null });
    expect([payload.prompt, payload.voiceProfileId, payload.targetWords]).toEqual([null, null, null]);
  });

  test('an existing template round-trips through the editor unchanged', () => {
    const t = template();
    const payload = draftToPayload(draftFromTemplate(t));
    expect(payload.headings).toEqual(
      t.headings.map((h) => ({
        text: null,
        prompt: null,
        voice_profile_id: null,
        target_words: null,
        ...h,
      })),
    );
    expect([payload.prompt, payload.voiceProfileId, payload.targetWords]).toEqual([
      'Focus on East Africa',
      'v-shared',
      700,
    ]);
  });

  test('numberHeadings marks the headings that carry a prompt', () => {
    expect(numberHeadings(template().headings).map((h) => h.hasPrompt)).toEqual([false, true]);
  });
});

describe('starting a brief from a template', () => {
  test('each section takes its heading prompt as guidance, and its voice and length', () => {
    const [context, findings] = template().headings.map(sectionFromTemplateHeading);
    expect(context).toMatchObject({ title: 'Context', guidance: undefined, voiceId: null, targetWords: null });
    expect(findings).toMatchObject({
      title: 'Findings',
      guidance: 'Lead with outcomes',
      voiceId: 'v-mine',
      targetWords: 150,
      status: 'pending',
    });
  });

  test('saved text starts the section as done, and sub-headings stay sub-sections', () => {
    const section = sectionFromTemplateHeading({ title: 'Detail', sub: true, text: 'Saved.' });
    expect(section).toMatchObject({ level: 2, status: 'done', progress: 100, content: 'Saved.' });
  });
});

describe('the template editor', () => {
  test('a heading prompt, voice and length are edited under the heading', async () => {
    const onSave = jest.fn().mockResolvedValue(undefined);
    const draft: TemplateDraft = {
      ...emptyTemplateDraft(),
      name: 'Board memo',
      headings: [draftHeading({ title: 'Findings', sub: false })],
    };
    render(<BriefTemplateModal draft={draft} voices={VOICES} onSave={onSave} onClose={jest.fn()} />);

    fireEvent.click(screen.getByRole('button', { name: 'Prompt' }));
    fireEvent.change(screen.getByLabelText('Prompt for “Findings”'), { target: { value: 'Cover 2020 onward' } });
    fireEvent.change(screen.getByLabelText('Voice and tone profile for Findings'), {
      target: { value: 'v-shared' },
    });
    fireEvent.change(screen.getByLabelText(/Brief prompt/), { target: { value: 'East Africa' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save template' }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    const payload = draftToPayload(onSave.mock.calls[0][0]);
    expect(payload.headings[0]).toMatchObject({ prompt: 'Cover 2020 onward', voice_profile_id: 'v-shared' });
    expect(payload.prompt).toBe('East Africa');
    expect(screen.getByRole('button', { name: 'Prompt ✓' })).toBeInTheDocument();
  });

  test('saving from a brief offers both switches and hides settings when prompts are off', () => {
    render(
      <BriefTemplateModal draft={fromBriefDraft()} voices={VOICES} onSave={jest.fn()} onClose={jest.fn()} />,
    );
    expect(screen.getByText('Save brief as template')).toBeInTheDocument();
    expect(screen.getByLabelText(/Brief prompt/)).toHaveValue('Whole brief');

    fireEvent.click(screen.getByRole('switch', { name: 'Include prompts and settings' }));

    expect(screen.queryByLabelText(/Brief prompt/)).toBeNull();
    expect(screen.queryByRole('button', { name: /^Prompt/ })).toBeNull();
  });

  test('editing an existing template says so', () => {
    render(
      <BriefTemplateModal
        draft={draftFromTemplate(template())}
        voices={VOICES}
        onSave={jest.fn()}
        onClose={jest.fn()}
      />,
    );
    expect(screen.getByText('Edit template')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Prompt ✓' })).toBeInTheDocument();
  });
});

describe('the voice picker', () => {
  test('a shared profile says whose it is', () => {
    render(<BriefVoiceSelect value={null} voices={VOICES} onChange={jest.fn()} emptyLabel="No voice" />);
    expect(screen.getByRole('option', { name: 'Field summary — shared by Priya' })).toBeInTheDocument();
  });

  test('a profile the user cannot see is shown as unavailable, not replaced', () => {
    render(<BriefVoiceSelect value="v-gone" voices={VOICES} onChange={jest.fn()} emptyLabel="No voice" />);
    const option = screen.getByRole('option', { name: UNAVAILABLE_VOICE_LABEL });
    expect(option).toBeDisabled();
    expect((screen.getByRole('combobox') as HTMLSelectElement).value).toBe('v-gone');
  });

  test('the Research panel hint says an unavailable voice is not applied', () => {
    expect(voiceHint('v-gone', null, null, null)).toMatch(/written without one/);
    expect(voiceHint(null, null, 'v-gone', null)).toMatch(/written without one/);
    expect(voiceHint(null, null, 'v-mine', MINE)).toBe(`Inherits the brief profile — ${MINE.instructions}`);
    expect(voiceHint(null, null, null, null)).toBe('No voice profile applied');
    expect(briefDefaultSuffix('v-gone', null)).toBe(' — unavailable');
  });
});

describe('the New brief dialog', () => {
  const open = (props: Partial<React.ComponentProps<typeof BriefNewModal>> = {}) => {
    const onSubmit = jest.fn<void, [NewBriefSubmit]>();
    render(
      <BriefNewModal
        templates={[template(), template({ id: 't-2', name: 'Plain', prompt: null, voice_profile_id: null, target_words: null })]}
        voices={VOICES}
        onSubmit={onSubmit}
        onClose={jest.fn()}
        {...props}
      />,
    );
    return onSubmit;
  };

  test('using a template starts with its prompt, voice and length', () => {
    const onSubmit = open({ initialTemplateId: 't-1' });
    expect(screen.getByLabelText(/Brief prompt/)).toHaveValue('Focus on East Africa');
    fireEvent.click(screen.getByRole('button', { name: /Create brief/ }));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      mode: 'manual',
      instructions: 'Focus on East Africa',
      voiceId: 'v-shared',
      targetWords: 700,
    });
  });

  test('picking a template in the Manual tab brings its defaults and marks prompted headings', () => {
    const onSubmit = open({ defaultTargetWords: 350 });
    fireEvent.click(screen.getByRole('tab', { name: 'Manual' }));
    fireEvent.change(screen.getByLabelText('Template'), { target: { value: 't-1' } });

    expect(within(screen.getByText("Headings you'll start with").parentElement as HTMLElement).getAllByText('prompt')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /Create brief/ }));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ voiceId: 'v-shared', targetWords: 700 });
  });

  test('a template without a length keeps the length already chosen', () => {
    const onSubmit = open({ defaultTargetWords: 350 });
    fireEvent.click(screen.getByRole('tab', { name: 'Manual' }));
    fireEvent.change(screen.getByLabelText('Template'), { target: { value: 't-2' } });
    fireEvent.click(screen.getByRole('button', { name: /Create brief/ }));
    expect(onSubmit.mock.calls[0][0]).toMatchObject({ instructions: '', voiceId: null, targetWords: 350 });
  });
});
