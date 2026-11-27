import React from 'react';
import axios from 'axios';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import BriefEvaluationTemplates from '../components/admin/testing/BriefEvaluationTemplates';
import { getAssertionSpecs } from '../components/admin/testing/assertionSpecs';

jest.mock('axios');
const api = axios as jest.Mocked<typeof axios>;
const dataset = { id: 'd', name:'Technical documents', capability:'brief' as const, data_source:'demo', created_at:'', updated_at:'' };
const template = { id:'t', name:'Maintenance', owner_name:'Lee', description:'Quarterly checks',
  section_count:1,headings:[{title:'Service history',sub:false}], prompt:'Compare quarterly costs.',
  voice_profile_id:'v',target_words:150 };
const voices = [{id:'v', name:'Operator guide', instructions:'Use direct address.',can_edit:true}];
const show = () => render(<BriefEvaluationTemplates dataset={dataset} onBack={jest.fn()} onViewExperiments={jest.fn()} />);

test('lists actual templates and opens the shared editor on the original, with its owner’s profile',async () => {
  api.get.mockImplementation(async url => ({data:url.endsWith('/voices') ? voices : url.endsWith('/t') ? template : [template]}));
  api.put.mockResolvedValue({data:template});
  show();
  fireEvent.click(await screen.findByRole('button',{name:'Edit Maintenance'}));
  const name = await screen.findByLabelText('Template name');
  expect(name).toHaveValue('Maintenance');
  expect(screen.getByRole('option',{name:/Operator guide/})).toBeInTheDocument();
  expect(screen.getByDisplayValue('Compare quarterly costs.')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'Delete Maintenance'})).toBeNull();
  fireEvent.change(name,{target:{value:'Revised maintenance'}});
  fireEvent.click(screen.getByRole('button',{name:'Save template'}));
  await waitFor(()=>expect(api.put).toHaveBeenCalledWith(expect.stringContaining('/testing/brief-templates/t'),expect.objectContaining({
    name:'Revised maintenance', voice_profile_id:'v',target_words:150,
    headings:[expect.objectContaining({title:'Service history'})],
  })));
  await waitFor(()=>expect(screen.queryByLabelText('Template name')).toBeNull());
});

test('explains how to add the first record and returns from the template editor without saving',async () => {
  api.get.mockResolvedValue({data:[]});
  show();
  expect(await screen.findByText('No Brief templates yet.')).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Create template'}));
  fireEvent.click(await screen.findByRole('button',{name:/Back to brief evaluation/}));
  expect(screen.queryByLabelText('Template name')).toBeNull();
  expect(api.post).not.toHaveBeenCalled();
  expect(getAssertionSpecs('brief').map(x => x.type)).toEqual(expect.arrayContaining(['brief_structure','brief_length','brief_paragraphs','brief_writing','brief_overlap','brief_intro_scope','brief_factual']));
});

test('owners see a deletion confirmation naming the original template', async () => {
  api.get.mockResolvedValue({data:[{...template,can_delete:true}]});
  show();
  fireEvent.click(await screen.findByRole('button',{name:'Delete Maintenance'}));
  expect(screen.getByText(/Delete “Maintenance” from Brief Central/)).toBeVisible();
  fireEvent.click(screen.getByRole('button',{name:'Cancel'}));
  expect(api.delete).not.toHaveBeenCalled();
});
