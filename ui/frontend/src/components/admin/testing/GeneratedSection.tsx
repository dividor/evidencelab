import React, { useId, useState } from 'react';
import type { BriefEvalClaim, BriefEvalReference, TestResult } from '../../../types/testing';

type SavedSource = { title?: string; page?: number | null; text?: string };
type ReferenceProps = { reference: BriefEvalReference; sources: SavedSource[] };

function Reference({ reference, sources, expanded }: ReferenceProps & { expanded?: boolean }) {
  const source = reference.source_position === null ? undefined : sources[reference.source_position];
  const heading = `[${reference.label}] ${source?.title || (source ? 'Untitled source' : 'Source unavailable')}`;
  const label = source?.page == null ? heading : `${heading} · p. ${source.page}`;
  const excerpt = <div className="testing-cited-excerpt">{source?.text || 'No passage text was saved for this citation.'}</div>;
  return expanded ? (
    <div className="testing-claim-source"><strong>{label}</strong>{excerpt}</div>
  ) : (
    <details className="testing-section-reference"><summary>{label}</summary>{excerpt}</details>
  );
}

function Claim({ claim, references, sources }: {
  claim: BriefEvalClaim; references: BriefEvalReference[]; sources: SavedSource[];
}) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <>
      {claim.parts.map((part, i) => part.marker ? (
        <button
          key={i} type="button" className="testing-claim-citation"
          aria-label={`${open ? 'Hide' : 'Show'} cited passages ${part.text}`}
          aria-expanded={open} aria-controls={panel} onClick={() => setOpen(!open)}
        >{part.text}</button>
      ) : <React.Fragment key={i}>{part.text}</React.Fragment>)}
      {open && (
        <div className="testing-claim-evidence" id={panel} role="group" aria-label="Cited passages for this claim">
          {claim.references.map(index => (
            <Reference key={index} reference={references[index]} sources={sources} expanded />
          ))}
        </div>
      )}
    </>
  );
}

export default function GeneratedSection({ result }: { result: TestResult }) {
  const output = result.actual_output;
  if (output?.capability !== 'brief') return null;
  const evidence = result.brief_evidence;
  const savedText = typeof output.summary === 'string' ? output.summary : '';
  const assignment = output.assignment as { target_words?: number } | undefined;
  const sources = (output.sources || []) as SavedSource[];
  return (
    <details className="testing-case-block testing-generated-section">
      <summary className="testing-case-label">Generated section</summary>
      {savedText && output.written !== false ? (
        <>
          <p>{String(output.words)} words{assignment?.target_words ? ` of ${assignment.target_words} requested` : ''}</p>
          <div className="testing-brief-prose">
            {evidence ? evidence.paragraphs.map((paragraph, p) => (
              <div className="testing-claim-paragraph" key={p}>
                {paragraph.map((claim, i) => (
                  <React.Fragment key={i}>
                    {i > 0 && ' '}
                    <Claim claim={claim} references={evidence.references} sources={sources} />
                  </React.Fragment>
                ))}
              </div>
            )) : savedText}
          </div>
          {evidence && evidence.references.length > 0 && (
            <div className="testing-section-references">
              <strong>References</strong>
              {evidence.references.map(ref => <Reference key={ref.label} reference={ref} sources={sources} />)}
            </div>
          )}
        </>
      ) : (
        <>
          <p>No section was written.</p>
          {Array.isArray(output.editorial_issues) && output.editorial_issues.map((issue, i) => (
            <p key={i}>{String(issue)}</p>
          ))}
        </>
      )}
    </details>
  );
}
