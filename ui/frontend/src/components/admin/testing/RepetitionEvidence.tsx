import React from 'react';
import type { AssertionResult } from '../../../types/testing';

interface SavedDraft {
  siblings?: { title: string; content?: string }[];
  assignment?: { heading?: string };
  summary?: string;
}

function Passage({ label, heading, quote, text }: {
  label: string; heading?: string; quote: string; text: string;
}) {
  const start = text.indexOf(quote);
  return <div className="testing-repetition-passage">
    <p><strong>{label}</strong> &middot; {heading}</p>
    <blockquote>{quote}</blockquote>
    <details><summary>Read full {label.toLowerCase()} section</summary>
      <div className="testing-cited-excerpt">{start < 0 ? text : <>
        {text.slice(0, start)}<mark>{quote}</mark>{text.slice(start + quote.length)}
      </>}</div>
    </details>
  </div>;
}

export default function RepetitionEvidence({ check, output }: {
  check: AssertionResult; output: SavedDraft;
}) {
  const pairs = check.repetitions || [];
  if (!pairs.length) return <p>{check.message}</p>;
  return <>
    <ol className="testing-repetition-list">{pairs.map((pair, index) => {
      const source = output.siblings?.[pair.source_index];
      return <li key={index}>
        <h4>Repetition {index + 1}</h4>
        <div className="testing-repetition-passages">
          <Passage label="Source" heading={source?.title} quote={pair.source_quote} text={source?.content || ''} />
          <Passage label="Target" heading={output.assignment?.heading} quote={pair.target_quote} text={output.summary || ''} />
        </div>
        {pair.assessment && <p><strong>Judge assessment</strong><br /><span>{pair.assessment}</span></p>}
        {!pair.assessment && pairs.length === 1 && <p><strong>Judge assessment for this section</strong><br /><span>{check.section_assessment}</span></p>}
      </li>;
    })}</ol>
    {(pairs.length > 1 || pairs[0].assessment) && <details>
      <summary>Overall judge assessment</summary><p>{check.section_assessment ?? check.message}</p>
    </details>}
  </>;
}
