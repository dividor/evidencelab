import axios from 'axios';
import API_BASE_URL from '../../config';
import type { BriefCheckRun, BriefFactCheckEvidenceRead, BriefFactCheckRead } from '../../types/testing';

/**
 * The Fact Checker of a saved brief: the completed citation check that still
 * covers the brief's cited passages (if any), every judged passage to
 * highlight with its verdict, any active run, and whether the reader can start a check. Requires the user module; auth
 * rides on the httpOnly cookie like the rest of Brief Central.
 */
export const getBriefFactCheck = async (briefId: string): Promise<BriefFactCheckRead> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/${briefId}/fact-check`);
  return res.data as BriefFactCheckRead;
};

/** The evidence behind one highlighted passage: the cited excerpts with the
 *  judge's quotes marked, as the API cuts them. */
export const getBriefFactCheckEvidence = async (
  briefId: string,
  checkId: string,
  passageId: number,
): Promise<BriefFactCheckEvidenceRead> => {
  const res = await axios.get(
    `${API_BASE_URL}/briefs/${briefId}/fact-check/${checkId}/passages/${passageId}`,
  );
  return res.data as BriefFactCheckEvidenceRead;
};

const runsUrl = (briefId: string) => `${API_BASE_URL}/briefs/${briefId}/fact-check/runs`;

export async function startFactCheck(briefId: string, modelCombo?: string | null): Promise<BriefCheckRun> {
  return (await axios.post(runsUrl(briefId), { model_combo: modelCombo })).data;
}

export async function readFactCheckRun(briefId: string, runId: string): Promise<BriefCheckRun> {
  return (await axios.get(`${runsUrl(briefId)}/${runId}`)).data;
}

export async function stopFactCheck(briefId: string, runId: string): Promise<BriefCheckRun> {
  return (await axios.post(`${runsUrl(briefId)}/${runId}/stop`)).data;
}
