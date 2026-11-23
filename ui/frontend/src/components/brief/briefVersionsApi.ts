import axios from 'axios';
import API_BASE_URL from '../../config';
import { BriefVersionItem, BriefVersionRead, RemoteBrief } from './briefTypes';

/**
 * Whole-brief versions of a signed-in brief. The API writes a version with
 * every change; the browser only lists, shows and restores them.
 */

export const listBriefVersions = async (briefId: string): Promise<BriefVersionItem[]> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/${briefId}/versions`);
  return res.data as BriefVersionItem[];
};

export const getBriefVersion = async (
  briefId: string,
  number: number,
): Promise<BriefVersionRead> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/${briefId}/versions/${number}`);
  return res.data as BriefVersionRead;
};

export const restoreBriefVersion = async (
  briefId: string,
  number: number,
): Promise<RemoteBrief> => {
  const res = await axios.post(`${API_BASE_URL}/briefs/${briefId}/versions/${number}/restore`);
  return res.data as RemoteBrief;
};
