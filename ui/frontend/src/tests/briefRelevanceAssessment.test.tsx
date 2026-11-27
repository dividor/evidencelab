import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import AssertionResultRow from '../components/admin/testing/AssertionResultRow';

const title = 'Relevance to the template and section';
const saved = {
  actual_output: { capability: 'brief', summary: 'Repair times fell [2].', words: 3, written: true,
    sources: [{ index: 2, title: 'Service log', text: 'Crews reported faster repairs.' }] },
  brief_evidence: {
    paragraphs: [[{ parts: [{ text: 'Repair times fell ' }, { text: '[2]', marker: true }, { text: '.' }], references: [0] }]],
    references: [{ label: '2', source_position: 0 }],
  },
};

test('shows deductions first and opens the positives, section and individual excerpts on request', async () => {
  render(<AssertionResultRow testResult={saved} result={{ type: 'llm_judge', label: title, passed: false,
    score: 0.7, message: 'The second workshop is missing.', relevance: {
      negatives: ['The second workshop is missing.'], positives: ['Describes the repair work.'],
    } }} />);
  fireEvent.click(screen.getByText(title));
  expect(await screen.findByText('The second workshop is missing.')).toBeVisible();
  const positives = screen.getByText('Positives:');
  expect(positives.closest('details')).not.toHaveAttribute('open');
  fireEvent.click(positives);
  expect(screen.getByText('Describes the repair work.')).toBeVisible();
  const section = screen.getByText('Section text and references');
  expect(section.closest('details')).not.toHaveAttribute('open');
  fireEvent.click(section);
  const ref = screen.getByText('[2] Service log');
  expect(ref.closest('details')).not.toHaveAttribute('open');
  fireEvent.click(ref);
  expect(screen.getByText('Crews reported faster repairs.')).toBeVisible();
});

test('keeps the original assessment available for earlier grades without structured findings', async () => {
  render(<AssertionResultRow testResult={saved} result={{ type: 'llm_judge', label: title,
    passed: false, score: 0.9, message: 'Historical assessment.' }} />);
  fireEvent.click(screen.getByText(title));
  fireEvent.click(await screen.findByText('Original assessment'));
  expect(screen.getByText('Historical assessment.')).toBeVisible();
  expect(screen.queryByText('Negatives:')).toBeNull();
});

test.each([true, false])('Word count shows section text and references when applicable is %s', async applicable => {
  const message = applicable ? '3 words of 5 requested.' : 'This section has no word target.';
  render(<AssertionResultRow testResult={saved} result={{ type: 'brief_length', passed: false, message, applicable }} />);
  fireEvent.click(screen.getByText('Word count'));
  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.queryByText('Section claims')).toBeNull();
  const section = screen.getByText('Section text and references');
  expect(section.closest('details')).not.toHaveAttribute('open');
  fireEvent.click(section);
  const reference = screen.getByText('[2] Service log');
  expect(reference.closest('details')).not.toHaveAttribute('open');
  fireEvent.click(reference);
  expect(screen.getByText('Crews reported faster repairs.')).toBeVisible();
});
