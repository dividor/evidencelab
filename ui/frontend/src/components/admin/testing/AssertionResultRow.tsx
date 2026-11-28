import React, { useState } from 'react';
import type { AssertionResult, TestResult } from '../../../types/testing';
import { judgeCriterionName } from './assertionSpecs';
import GeneratedSection, { AssertionEvidence } from './GeneratedSection';
import RepetitionEvidence from './RepetitionEvidence';
import { formatScore } from './testingFormat';

const briefCheckLabels: Record<string, string> = {
  brief_relevance: 'Relevance to the template and section', brief_factual: 'Factual support from citations', brief_voice: 'Selected voice and tone profile', brief_writing: 'Writing quality', brief_paragraphs: 'One-sentence paragraphs',
  brief_intro_scope: 'Introduction scope', brief_length: 'Word count', brief_structure: 'Format and citations', brief_overlap: 'Cross-section repetition',
};

const expectationName = (result: AssertionResult) => result.type === 'llm_judge' || result.type === 'brief_writing'
    ? judgeCriterionName(result.type, result.rubric, result.label)
    : result.label || briefCheckLabels[result.type] || result.type.replace(/_/g, ' ');

function ungradedStatus(result: AssertionResult) {
  if (result.not_run) return 'Not graded';
  if (result.error) return 'Grading error';
  return result.applicable === false ? 'Not applicable' : '';
}

function RelevanceAssessment({ result }: { result: AssertionResult }) {
  if (!result.relevance) return <details><summary>Original assessment</summary><p>{result.message}</p></details>;
  const { negatives, positives } = result.relevance;
  return <>
    <p><strong>Negatives:</strong> {negatives.length === 0 && 'None.'}</p>
    {negatives.map((item, index) => <p key={index}>{item}</p>)}
    <details><summary>Positives:</summary>
      {positives.length ? positives.map((item, index) => <p key={index}>{item}</p>) : <p>None recorded.</p>}
    </details>
  </>;
}

type ResultProps = { result: AssertionResult; testResult: Pick<TestResult, 'actual_output' | 'brief_evidence'> };

function showsSectionWithClaims(result: AssertionResult) {
  return ['brief_writing', 'brief_paragraphs', 'brief_structure'].includes(result.type)
    || (result.type === 'llm_judge' && expectationName(result) === 'Paragraph development and flow');
}

function BriefAssessment({ result, testResult }: ResultProps) {
  if (result.type === 'brief_overlap') return <RepetitionEvidence check={result} output={testResult.actual_output!} />;
  if (result.type === 'brief_relevance' || result.relevance || result.label === briefCheckLabels.brief_relevance) return <>
    <RelevanceAssessment result={result} />
    <GeneratedSection result={testResult} label="Section text and references" />
  </>;
  if (result.type === 'brief_length') return <>
    <p className="testing-assertion-result-message">{result.message}</p>
    <GeneratedSection result={testResult} label="Section text and references" />
  </>;
  const evidence = <AssertionEvidence assessment={result} result={testResult} />;
  if (result.factual_support || result.type === 'brief_factual') return <>
    {evidence}
    {result.message && (testResult.brief_evidence
      ? <details><summary>Original section assessment</summary><p>{result.message}</p></details>
      : <p>{result.message}</p>)}
  </>;
  return <>
    <p className="testing-assertion-result-message">{result.message}</p>
    {showsSectionWithClaims(result) && <GeneratedSection result={testResult} label="Section text and references" />}
    {evidence}
  </>;
}

const AssertionResultRow: React.FC<ResultProps> = ({ result, testResult }) => {
  const [open, setOpen] = useState(false);
  const label = expectationName(result);
  const status = ungradedStatus(result);
  const hasSectionDetails = testResult.actual_output?.capability === 'brief'
    && (result.type === 'brief_length' || showsSectionWithClaims(result));
  if (status && !hasSectionDetails && !result.claim_grades?.length) return <div className="testing-assertion-result">
    <strong>{label}</strong> <span>{status}</span><p>{result.message}</p>
  </div>;
  const heading = <>
    <span className={`testing-badge testing-badge-${result.passed ? 'pass' : 'fail'}`}>{status || (result.passed ? 'pass' : 'fail')}</span>
    <span className="testing-assertion-result-type">{label}</span>
    {result.score !== undefined && <span className="testing-assertion-result-score">score: {formatScore(result.score)}</span>}
  </>;
  const prompts = <>
    {result.rubric && <details><summary>Grading criterion</summary><div>{result.rubric}</div></details>}
    {result.judge_prompt && <details><summary>Full prompt sent to the LLM</summary><pre className="testing-pre testing-pre-scroll">{result.judge_prompt}</pre></details>}
  </>;
  const detail = <><p className="testing-assertion-result-message">{result.message}</p>{prompts}</>;
  if (testResult.actual_output?.capability !== 'brief') return <div className="testing-assertion-result">{heading}{detail}</div>;
  const profile = (testResult.actual_output.assignment as { voice_profile?: { name: string; instructions: string } } | undefined)?.voice_profile;
  return (
    <details className="testing-assertion-result testing-brief-assertion" onToggle={e => setOpen(e.currentTarget.open)}>
      <summary><span className="testing-disclosure-arrow" aria-hidden="true" />{heading}</summary>
      {open && <div className="testing-assertion-body">
        {result.type === 'brief_voice' && profile && <div><strong>{profile.name}</strong><p>{profile.instructions}</p></div>}
        <BriefAssessment result={result} testResult={testResult} />
        {prompts}
      </div>}
    </details>
  );
};

export default AssertionResultRow;
