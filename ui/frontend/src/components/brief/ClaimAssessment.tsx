import React from 'react';
import './claimAssessment.css';
import type { AssertionResult } from '../../types/testing';
import { VERDICT_LABEL, VERDICT_TONE } from '../admin/testing/citationCheckFormat';
import { formatScore } from '../admin/testing/testingFormat';

type ClaimGrade = NonNullable<AssertionResult['claim_grades']>[number];

function ClaimScore({ grade, threshold, showPass }: { grade: ClaimGrade; threshold?: number | null; showPass: boolean }) {
  if (grade.error) return <span>{grade.outcome === 'missing_source' ? 'Cited excerpt unavailable' : 'Grading error'}</span>;
  return <>
    {grade.verdict && <span className={`testing-status testing-status-${VERDICT_TONE[grade.verdict]}`}>{VERDICT_LABEL[grade.verdict]}</span>}
    {grade.score != null && <span>Score {formatScore(grade.score)}</span>}
    {showPass && grade.passed != null && <span>{grade.passed ? 'Pass' : 'Fail'}</span>}
    {threshold != null && <span>Required {formatScore(threshold)}</span>}
  </>;
}

export function EvidenceGaps({ verdict, unmet }: Pick<ClaimGrade, 'verdict' | 'unmet'>) {
  if (verdict !== 'partially_supported' || !unmet?.length) return null;
  return <div>
    <strong>What the evidence does not establish</strong>
    <ul className="claim-evidence-gaps">{unmet.map((gap, i) => <li key={i}>{gap}</li>)}</ul>
  </div>;
}

export function ClaimAssessment({ number, text, grade, threshold, showPass = true }: {
  number: number; text: string; grade?: ClaimGrade; threshold?: number | null; showPass?: boolean;
}) {
  return <>
    <div className="testing-claim-heading">
      <strong>Claim {number}</strong>
      {grade && <ClaimScore grade={grade} threshold={threshold} showPass={showPass} />}
    </div>
    <blockquote className="claim-verbatim"><q>{text}</q></blockquote>
    {grade && <section className="testing-claim-reason"><h4>Judge assessment</h4><p>{grade.reason}</p></section>}
    {grade && <EvidenceGaps verdict={grade.verdict} unmet={grade.unmet} />}
  </>;
}

export function ClaimReference({ number, title, page, children }: {
  number: string | number | null; title: string; page?: number | null; children: React.ReactNode;
}) {
  return <details className="testing-section-reference">
    <summary>[{number}] {title}{page != null && ` · p. ${page}`}</summary>
    {children}
  </details>;
}
