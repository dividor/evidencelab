import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import BriefCaseEditor from '../components/admin/testing/BriefCaseEditor';
import { getAssertionSpecs } from '../components/admin/testing/assertionSpecs';

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
    ...testCase.input, guidance: 'Compare unit costs.', voice: '',
    siblings: testCase.input.siblings,
    children: [{ title: 'Personnel', content: 'Five people took part.', level: 2 }],
  });
  expect(getAssertionSpecs('brief').map(x => x.type)).toEqual(expect.arrayContaining(['brief_structure','brief_length','brief_paragraphs','brief_overlap','brief_intro_scope','llm_judge']));
});
