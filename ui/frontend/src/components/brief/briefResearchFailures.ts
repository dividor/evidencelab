import type { BriefSection } from './briefTypes';

const failureKey = (briefId: string) => `evidencelab_brief_research_failures:${briefId}`;

type StoredFailure = NonNullable<BriefSection['researchFailure']> & {
  currentRunId: string | null;
};

export const researchFailureSnapshot = (sections: BriefSection[]): string => JSON.stringify(
  sections.flatMap((section) => section.researchFailure
    ? [[section.id, { ...section.researchFailure, currentRunId: section.currentRunId ?? null }]]
    : []),
);

export const storeResearchFailures = (briefId: string, snapshot: string): void => {
  const key = failureKey(briefId);
  if (snapshot === '[]') sessionStorage.removeItem(key);
  else sessionStorage.setItem(key, snapshot);
};

export const readResearchFailures = (briefId: string): Map<string, StoredFailure> => {
  const stored = sessionStorage.getItem(failureKey(briefId));
  if (!stored) return new Map();
  try {
    return new Map(JSON.parse(stored));
  } catch {
    sessionStorage.removeItem(failureKey(briefId));
    return new Map();
  }
};
