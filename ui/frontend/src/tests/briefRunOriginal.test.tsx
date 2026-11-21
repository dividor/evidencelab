import { fireEvent, render, screen, within } from '@testing-library/react';
import { BriefRunOriginal, shortChunkId } from '../components/brief/BriefRunOriginal';
import { BriefSectionAudit } from '../components/brief/BriefSectionAudit';
import type {
  SectionAuditEntry,
  SectionRunDetail,
  SectionRunSummary,
} from '../components/brief/briefTypes';

/**
 * The stored original of a section run (Section History → original): the
 * agent's text, shown formatted with its own [n] numbers kept, or raw exactly
 * as returned; the table of where each number went; and the history row's
 * link to it.
 */

const CONTENT =
  "## WFP's response to El Niño\n\n" +
  'WFP scaled up food assistance [92, 147].\n\n' +
  'In **Ethiopia**, WFP provided direct food assistance [1, 2].';

const CHUNK = 'd0a49400-e0ac-5498-8d3e-eb2e061cf413';

const RUN: SectionRunSummary = {
  id: 'r2',
  mode: 'generate',
  at: Date.UTC(2026, 9, 7, 7, 30),
  status: 'current',
  sourcesRetained: 'exact',
  mapping: { '1': 's45' },
  unresolved: [{ n: 147, reason: 'no-source' }],
  rejected: [],
  sourceCount: 132,
  citedCount: 24,
};

const DETAIL: SectionRunDetail = {
  ...RUN,
  sectionId: 'sec-1',
  content: CONTENT,
  sources: [
    {
      chunkId: CHUNK,
      docId: 'd1',
      title: "Ethiopia - An evaluation of WFP's Portfolio (2012-2017)",
      text: 'Excerpt.',
      score: 0.9,
      index: 1,
      page: 67,
    },
  ],
  displayNumbers: { '1': 13 },
};

const renderOriginal = () =>
  render(
    <BriefRunOriginal title="WFP's response to El Niño" detail={DETAIL} error={null} onClose={() => {}} />,
  );

test('the text is formatted by default, keeping the agent’s own numbers', () => {
  renderOriginal();
  const text = screen.getByTestId('original-formatted');

  expect(within(text).getByRole('heading', { name: "WFP's response to El Niño" })).toBeInTheDocument();
  expect(within(text).getByText('Ethiopia').tagName).toBe('STRONG');
  expect(text).toHaveTextContent('WFP scaled up food assistance [92, 147].');
  expect(text).not.toHaveTextContent('##');
});

test('Raw shows the markdown exactly as the agent returned it', () => {
  const { container } = renderOriginal();

  fireEvent.click(screen.getByRole('button', { name: 'Raw' }));

  expect(screen.getByRole('button', { name: 'Raw' })).toHaveAttribute('aria-pressed', 'true');
  expect(screen.queryByTestId('original-formatted')).toBeNull();
  expect(container.querySelector('pre')?.textContent).toBe(CONTENT);
});

test('the number table shortens a chunk id and keeps the whole id as its tooltip', () => {
  renderOriginal();
  const chunk = screen.getByTitle(CHUNK);

  expect(chunk).toHaveTextContent('d0a49400…');
  const row = chunk.closest('tr') as HTMLElement;
  expect(within(row).getByText('[1]')).toBeInTheDocument();
  expect(within(row).getByText('[13]')).toBeInTheDocument();
  expect(within(row).getByText('67')).toBeInTheDocument();
});

test('a marker with no source is explained above the text', () => {
  renderOriginal();

  expect(screen.getByRole('status')).toHaveTextContent('[?147]');
});

test('shortChunkId leaves a short id alone', () => {
  expect(shortChunkId('abc')).toBe('abc');
  expect(shortChunkId(CHUNK)).toBe('d0a49400…');
});

test('a history row links to its original in lower case, like its other links', () => {
  const entry: SectionAuditEntry = {
    id: 'a1',
    kind: 'generate',
    at: RUN.at,
    question: "WFP's response to El Niño",
    runId: 'r2',
  };
  render(
    <BriefSectionAudit
      title="WFP's response to El Niño"
      audit={[entry]}
      runs={[RUN]}
      onViewOriginal={() => {}}
      onClose={() => {}}
    />,
  );

  expect(screen.getByRole('button', { name: '· original' })).toBeInTheDocument();
});
