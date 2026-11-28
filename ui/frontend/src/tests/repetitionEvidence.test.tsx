import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import RepetitionEvidence from '../components/admin/testing/RepetitionEvidence';

const output = {
  assignment: {heading: 'Progress'}, summary: 'New context. Waiting times fell. Costs rose.',
  siblings: [{title:'Operations',content:'Earlier context. Queues shortened.'}, {title:'Finance',content:'Expenses grew.'}],
};
const check = {type:'brief_overlap', message:'Two findings recur.', repetitions:[
  {source_index:0, source_quote:'Queues shortened.', target_quote:'Waiting times fell.', assessment:'Both passages report shorter waits.'},
  {source_index:1, source_quote:'Expenses grew.', target_quote:'Costs rose.', assessment:'Both passages report higher costs.'},
]};

test('lists each repetition with its passages, separate assessment, and independently expandable full text', () => {
  render(<RepetitionEvidence check={check} output={output} />);
  const [first, second] = screen.getAllByRole('listitem').map(item => within(item));
  expect(first.getByText('Both passages report shorter waits.')).toBeVisible();
  expect(second.getByText('Both passages report higher costs.')).toBeVisible();
  expect(first.getByText('Queues shortened.',{selector:'blockquote'})).toBeVisible();
  expect(first.getByText('Waiting times fell.',{selector:'blockquote'})).toBeVisible();
  const source = first.getByText('Read full source section').closest('details')!;
  const target = first.getByText('Read full target section').closest('details')!;
  expect(source.open).toBe(false);
  fireEvent.click(first.getByText('Read full source section'));
  expect(source.open).toBe(true);
  expect(source).toHaveTextContent(output.siblings[0].content);
  expect(source.querySelector('mark')).toHaveTextContent('Queues shortened.');
  expect(target.open).toBe(false);
  fireEvent.click(first.getByText('Read full target section'));
  expect(target).toHaveTextContent(output.summary);
});

test('shows the original verdict when there are no identified repetitions', () => {
  render(<RepetitionEvidence check={{type:'brief_overlap',message:'The sections report different outcomes.', repetitions:[]}} output={output} />);
  expect(screen.getByText('The sections report different outcomes.')).toBeVisible();
  expect(screen.queryByRole('listitem')).toBeNull();
});

test('labels the saved section assessment when an older judge gave one reason for a single pair', () => {
  render(<RepetitionEvidence check={{type:'brief_overlap',message:'Original verdict with appended quotes.',section_assessment:'One shared result.',repetitions:[
    {source_index:0, source_quote:'Queues shortened.', target_quote:'Waiting times fell.'},
  ]}} output={output} />);
  expect(screen.getByText('Judge assessment for this section')).toBeVisible();
  expect(screen.getByText('One shared result.')).toBeVisible();
  expect(screen.queryByText('Original verdict with appended quotes.')).toBeNull();
});
