import axios from 'axios';
import API_BASE_URL from '../../config';
import {
  BriefListItem,
  BriefTemplate,
  BriefTemplateHeading,
  RemoteBrief,
  SavedBrief,
  VoiceProfile,
} from './briefTypes';

/**
 * Axios client for the Brief Central backend (briefs, shares, templates and
 * voice & tone profiles). All endpoints require the user module: auth rides on
 * the httpOnly cookie + the global axios CSRF interceptor.
 */

// List endpoints must return JSON arrays; anything else (an HTML error page, a
// proxy error object) is a hard failure surfaced to the caller.
const expectArray = <T>(data: unknown, what: string): T[] => {
  if (!Array.isArray(data)) throw new Error(`Unexpected ${what} response`);
  return data as T[];
};

export const listMyBriefs = async (): Promise<BriefListItem[]> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/`);
  return expectArray<BriefListItem>(res.data, 'briefs');
};

export const listSharedBriefs = async (): Promise<BriefListItem[]> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/shared`);
  return expectArray<BriefListItem>(res.data, 'shared briefs');
};

export const getBrief = async (id: string): Promise<RemoteBrief> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/${id}`);
  return res.data as RemoteBrief;
};

export const createBrief = async (args: {
  title: string;
  query: string | null;
  dataSource: string | null;
  voiceProfileId: string | null;
  content: SavedBrief;
}): Promise<RemoteBrief> => {
  const res = await axios.post(`${API_BASE_URL}/briefs/`, {
    title: args.title,
    query: args.query,
    data_source: args.dataSource,
    voice_profile_id: args.voiceProfileId,
    content: args.content,
  });
  return res.data as RemoteBrief;
};

export const updateBrief = async (
  id: string,
  args: {
    title?: string;
    query?: string | null;
    voiceProfileId?: string | null;
    content?: SavedBrief;
  },
): Promise<RemoteBrief> => {
  const res = await axios.put(`${API_BASE_URL}/briefs/${id}`, {
    title: args.title,
    query: args.query,
    voice_profile_id: args.voiceProfileId,
    content: args.content,
  });
  return res.data as RemoteBrief;
};

export const deleteBriefRemote = async (id: string): Promise<void> => {
  await axios.delete(`${API_BASE_URL}/briefs/${id}`);
};

/** People and groups matching a share-dialog query (min 2 characters). */
export interface ShareSuggestions {
  users: Array<{ email: string; name: string }>;
  groups: Array<{ name: string }>;
}

export const searchShareTargets = async (q: string): Promise<ShareSuggestions> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/share-targets`, { params: { q } });
  const data = res.data as Partial<ShareSuggestions>;
  return { users: data.users || [], groups: data.groups || [] };
};

export const addBriefShare = async (
  briefId: string,
  target: string,
): Promise<RemoteBrief> => {
  const res = await axios.post(`${API_BASE_URL}/briefs/${briefId}/shares`, { target });
  return res.data as RemoteBrief;
};

export const removeBriefShare = async (
  briefId: string,
  shareId: string,
): Promise<void> => {
  await axios.delete(`${API_BASE_URL}/briefs/${briefId}/shares/${shareId}`);
};

// ---- templates ----

export const listTemplates = async (): Promise<BriefTemplate[]> => {
  const res = await axios.get(`${API_BASE_URL}/brief-templates/`);
  return expectArray<BriefTemplate>(res.data, 'templates');
};

export const createTemplate = async (args: {
  name: string;
  description: string | null;
  headings: BriefTemplateHeading[];
  withText: boolean;
}): Promise<BriefTemplate> => {
  const res = await axios.post(`${API_BASE_URL}/brief-templates/`, {
    name: args.name,
    description: args.description,
    headings: args.headings,
    with_text: args.withText,
  });
  return res.data as BriefTemplate;
};

export const deleteTemplate = async (id: string): Promise<void> => {
  await axios.delete(`${API_BASE_URL}/brief-templates/${id}`);
};

export const recordTemplateUse = async (id: string): Promise<BriefTemplate> => {
  const res = await axios.post(`${API_BASE_URL}/brief-templates/${id}/use`);
  return res.data as BriefTemplate;
};

// ---- voice profiles ----

export const listVoiceProfiles = async (): Promise<VoiceProfile[]> => {
  const res = await axios.get(`${API_BASE_URL}/voice-profiles/`);
  return expectArray<VoiceProfile>(res.data, 'voice profiles');
};

export const createVoiceProfile = async (args: {
  name: string;
  description: string | null;
  instructions: string;
}): Promise<VoiceProfile> => {
  const res = await axios.post(`${API_BASE_URL}/voice-profiles/`, args);
  return res.data as VoiceProfile;
};

export const updateVoiceProfile = async (
  id: string,
  args: { name: string; description: string | null; instructions: string },
): Promise<VoiceProfile> => {
  const res = await axios.put(`${API_BASE_URL}/voice-profiles/${id}`, args);
  return res.data as VoiceProfile;
};

export const deleteVoiceProfile = async (id: string): Promise<void> => {
  await axios.delete(`${API_BASE_URL}/voice-profiles/${id}`);
};
