import React from 'react';
import { render, screen } from '@testing-library/react';
import { IntroHeadingWarning } from '../components/brief/BriefDocument';
import { BriefSectionAudit } from '../components/brief/BriefSectionAudit';

jest.mock('../config', () => ({ __esModule: true, default: '/api', API_KEY: undefined, USER_MODULE: false }));

describe('introduction heading warning', () => {
  test('shows how many headings an introduction kept', () => {
    render(<IntroHeadingWarning headings={2} />);
    expect(screen.getByRole('status')).toHaveTextContent('This introduction still has 2 headings of its own');
  });

  test('uses the singular for one heading', () => {
    render(<IntroHeadingWarning headings={1} />);
    expect(screen.getByRole('status')).toHaveTextContent('still has 1 heading of its own');
  });

  test('shows nothing when there are none', () => {
    const { container } = render(<IntroHeadingWarning />);
    expect(container).toBeEmptyDOMElement();
  });
});

test('the Log shows a note on the run that kept an introduction with headings', () => {
  render(
    <BriefSectionAudit
      title="Education outcomes"
      audit={[{ id: 'e1', kind: 'generate', at: Date.now(), question: 'Education outcomes', note: 'Kept with 1 heading.' }]}
      pendingEntryId={null}
      onShowChanges={jest.fn()}
      onClose={jest.fn()}
    />,
  );
  expect(screen.getByText('Note')).toBeInTheDocument();
  expect(screen.getByText(/Kept with 1 heading\./)).toBeInTheDocument();
});
