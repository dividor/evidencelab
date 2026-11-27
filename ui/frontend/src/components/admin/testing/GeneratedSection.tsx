import React, { useId, useState } from 'react';
import type { AssertionResult, BriefEvalClaim, BriefEvalReference, TestResult } from '../../../types/testing';

import { VERDICT_LABEL, VERDICT_TONE } from './citationCheckFormat';
import { formatScore } from './testingFormat';

type SavedSource = { title?: string; page?: number | null; text?: string; headings?: string[] };
type ReferenceProps = { reference: BriefEvalReference; sources: SavedSource[] };

function Reference({ reference, sources, expanded }: ReferenceProps & { expanded?: boolean }) {
  const source = reference.source_position === null ? undefined : sources[reference.source_position];
  const heading = `[${reference.label}] ${source?.title || (source ? 'Untitled source' : 'Source unavailable')}`;
  const label = source?.page == null ? heading : `${heading} · p. ${source.page}`;
  const excerpt = <div className="testing-cited-excerpt">{source?.headings?.length ? <p>{source.headings.join(' › ')}</p> : null}{source?.text || 'No passage text was saved for this citation.'}</div>;
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

type ClaimGrade = NonNullable<AssertionResult['claim_grades']>[number];

function ClaimScore({ grade, threshold }: { grade: ClaimGrade; threshold?: number }) {
  if (grade.error) return <span>{grade.outcome === 'missing_source' ? 'Cited excerpt unavailable' : 'Grading error'}</span>;
  return <>
    {grade.verdict && <span className={`testing-status testing-status-${VERDICT_TONE[grade.verdict]}`}>{VERDICT_LABEL[grade.verdict]}</span>}
    <span>Score {formatScore(grade.score)}</span>
    <span>{grade.passed ? 'Pass' : 'Fail'}</span>
    {threshold !== undefined && <span>Required {formatScore(threshold)}</span>}
  </>;
}

function PartialSupport({ grade }: { grade: ClaimGrade }) {
  if (grade.verdict !== 'partially_supported' || !grade.unmet?.length) return null;
  return <div>
    <strong>What the evidence does not establish</strong>
    <ul className="claim-evidence-gaps">{grade.unmet.map((gap, i) => <li key={i}>{gap}</li>)}</ul>
  </div>;
}

export function AssertionEvidence({ assessment, result }: { assessment: AssertionResult; result: Pick<TestResult, "actual_output" | "brief_evidence"> }) {
  const evidence = result.brief_evidence;
  if (!evidence) return null;
  const sources = (result.actual_output?.sources || []) as SavedSource[];
  const quoted = new Set(assessment.quoted_claims || []);
  const factual = assessment.factual_support || assessment.type === 'brief_factual';
  const grades = new Map(assessment.claim_grades?.map(grade => [grade.claim, grade]));
  const claims = evidence.paragraphs.flat().map((claim, index) => {
    const grade = grades.get(index + 1);
    return (
      <div className="testing-evidence-claim" key={index}>
        <div className="testing-claim-heading">
          <strong>Claim {index + 1}</strong>
          {grade && <ClaimScore grade={grade} threshold={assessment.threshold} />}
        </div>
        <div>{claim.parts.map(part => part.text).join('')}</div>
        {grade && <p className="testing-claim-reason"><strong>Judge assessment</strong> {grade.reason}</p>}
        {grade && <PartialSupport grade={grade} />}
        {claim.references.length ? claim.references.map(ref => (
          <Reference key={ref} reference={evidence.references[ref]} sources={sources} />
        )) : <small>No citation on this sentence.</small>}
      </div>
    );
  });
  if (factual) return <div className="testing-factual-claims">
    {!assessment.claim_grades && <small>This run recorded a single grade for the section.</small>}
    {claims}
  </div>;
  if (!quoted.size) return <div className="testing-assessment-claims"><strong>Section claims</strong>{claims}</div>;
  return (
    <div className="testing-assessment-claims">
      <strong>Quoted in this assessment</strong>
      {claims.filter((_, i) => quoted.has(i))}
      {quoted.size < claims.length && (
        <details><summary>Other section claims ({claims.length - quoted.size})</summary>
          {claims.filter((_, i) => !quoted.has(i))}
        </details>
      )}
    </div>
  );
}

export default function GeneratedSection({ result, label = 'Generated section' }: { result: Pick<TestResult, "actual_output" | "brief_evidence">; label?: string }) {
  const output = result.actual_output;
  if (output?.capability !== 'brief') return null;
  const evidence = result.brief_evidence;
  const savedText = typeof output.summary === 'string' ? output.summary : '';
  const assignment = output.assignment as { target_words?: number } | undefined;
  const sources = (output.sources || []) as SavedSource[];
  return (
    <details className="testing-case-block testing-generated-section">
      <summary className="testing-case-label">{label}</summary>
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
