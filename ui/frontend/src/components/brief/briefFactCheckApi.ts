import axios from 'axios';
import API_BASE_URL from '../../config';
import type { BriefFactCheckEvidenceRead, BriefFactCheckRead } from '../../types/testing';

/**
 * The Fact Checker of a saved brief: the completed citation check that still
 * covers the brief's cited passages (if any), every judged passage to
 * highlight with its verdict, and the legend. Requires the user module; auth
 * rides on the httpOnly cookie like the rest of Brief Central.
 */
export const getBriefFactCheck = async (briefId: string): Promise<BriefFactCheckRead> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/${briefId}/fact-check`);
  return res.data as BriefFactCheckRead;
};

const acceptanceUrl = (briefId: string, checkId: string, passageId: number): string =>
  `${API_BASE_URL}/briefs/${briefId}/fact-check/${checkId}/passages/${passageId}/acceptance`;

/** Accept the citation of one judged passage, with an optional comment. The
 *  API answers with the Fact Checker as it now stands. */
export const acceptBriefFactCheckPassage = async (
  briefId: string,
  checkId: string,
  passageId: number,
  comment: string,
): Promise<BriefFactCheckRead> => {
  const res = await axios.put(acceptanceUrl(briefId, checkId, passageId), { comment });
  return res.data as BriefFactCheckRead;
};

/** Withdraw the acceptance of one judged passage. */
export const withdrawBriefFactCheckAcceptance = async (
  briefId: string,
  checkId: string,
  passageId: number,
): Promise<BriefFactCheckRead> => {
  const res = await axios.delete(acceptanceUrl(briefId, checkId, passageId));
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
