import axios from 'axios';
import API_BASE_URL from '../../config';
import type { BriefFactCheckRead } from '../../types/testing';

/**
 * The Fact Checker of a saved brief: the completed citation check that judged
 * the brief's current cited passages (if any) and the passages to highlight
 * for the verdicts the reader's groups chose. Requires the user module; auth
 * rides on the httpOnly cookie like the rest of Brief Central.
 */
export const getBriefFactCheck = async (briefId: string): Promise<BriefFactCheckRead> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/${briefId}/fact-check`);
  return res.data as BriefFactCheckRead;
};
