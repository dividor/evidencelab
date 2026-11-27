import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import BriefCaseEditor from '../components/admin/testing/BriefCaseEditor';
import { getAssertionSpecs } from '../components/admin/testing/assertionSpecs';
import { listVoiceProfiles } from '../components/brief/briefCentralApi';

jest.mock('../components/brief/briefCentralApi', () => ({ listVoiceProfiles: jest.fn() }));
beforeEach(() => { (listVoiceProfiles as jest.Mock).mockResolvedValue([]); });

test('saves section scope, target and existing sections while retaining editorial references', () => {
  const save = jest.fn();
  const reference = { source: { text: 'Documented observation.' } };
  const testCase = { id: 'c', dataset_id: 'd', created_at: '', updated_at: '', input: {
    query: 'Operations', heading: 'Cost', target_words: 150, reference_standard: reference,
    siblings: [{ title: 'Duration', content: 'The survey took a week.' }],
  } };
  render(<BriefCaseEditor initialCase={testCase} dataSource="demo" saving={false}
    submitLabel="Save" onSubmit={save} onCancel={jest.fn()} />);
  fireEvent.change(screen.getByLabelText('Section instructions'), { target: { value: 'Compare unit costs.' } });
  fireEvent.click(screen.getByText('Add another section'));
  fireEvent.change(screen.getAllByLabelText('Heading')[1], { target: { value: 'Personnel' } });
  fireEvent.change(screen.getAllByLabelText('Existing text')[1], { target: { value: 'Five people took part.' } });
  fireEvent.change(screen.getAllByLabelText('Position in the outline')[1], { target: { value: 'child' } });
  fireEvent.click(screen.getByText('Save'));
  expect(save.mock.calls[0][0].input).toEqual({
    ...testCase.input, guidance: 'Compare unit costs.', voice: '', voice_profile: null,
    siblings: testCase.input.siblings,
    children: [{ title: 'Personnel', content: 'Five people took part.', level: 2 }],
  });
  expect(getAssertionSpecs('brief').map(x => x.type)).toEqual(expect.arrayContaining(['brief_structure','brief_length','brief_paragraphs','brief_writing','brief_overlap','brief_intro_scope','llm_judge']));
});

test('saves the instructions of the selected voice profile with the case', async () => {
  const selected = { id: 'v1', name: 'Operator guide', instructions: 'Address the operator directly.' };
  (listVoiceProfiles as jest.Mock).mockResolvedValue([selected]);
  const save = jest.fn();
  render(<BriefCaseEditor dataSource="demo" saving={false} submitLabel="Save" onSubmit={save} onCancel={jest.fn()} />);
  await screen.findByRole('option', { name: 'Operator guide' });
  fireEvent.change(screen.getByLabelText('Voice and tone profile'), { target: { value: 'v1' } });
  fireEvent.change(screen.getByLabelText('Brief topic'), { target: { value: 'Operations' } });
  fireEvent.change(screen.getByLabelText('Section to generate'), { target: { value: 'Safety' } });
  fireEvent.click(screen.getByText('Save'));
  expect(save.mock.calls[0][0].input.voice_profile).toEqual(selected);
});
