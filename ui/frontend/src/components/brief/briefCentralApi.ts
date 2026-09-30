import axios from 'axios';
import API_BASE_URL from '../../config';
import {
  BriefListItem,
  BriefShareTarget,
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

/** Every brief in the system, with its owner (administrators only). */
export const listAllBriefs = async (): Promise<BriefListItem[]> => {
  const res = await axios.get(`${API_BASE_URL}/briefs/all`);
  return expectArray<BriefListItem>(res.data, 'all briefs');
};

/** Copy a brief into a new one the user owns (their own, or any for admins). */
export const copyBrief = async (id: string): Promise<RemoteBrief> => {
  const res = await axios.post(`${API_BASE_URL}/briefs/${id}/copy`);
  return res.data as RemoteBrief;
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

/** Everything a template stores, as the editor and save-from-brief send it. */
export interface TemplatePayload {
  name: string;
  description: string | null;
  headings: BriefTemplateHeading[];
  withText: boolean;
  prompt: string | null;
  voiceProfileId: string | null;
  targetWords: number | null;
}

const templateBody = (args: TemplatePayload) => ({
  name: args.name,
  description: args.description,
  headings: args.headings,
  with_text: args.withText,
  prompt: args.prompt,
  voice_profile_id: args.voiceProfileId,
  target_words: args.targetWords,
});

/** The user's own templates, then templates shared with them. */
export const listTemplates = async (): Promise<BriefTemplate[]> => {
  const res = await axios.get(`${API_BASE_URL}/brief-templates/`);
  return expectArray<BriefTemplate>(res.data, 'templates');
};

export const createTemplate = async (args: TemplatePayload): Promise<BriefTemplate> => {
  const res = await axios.post(`${API_BASE_URL}/brief-templates/`, templateBody(args));
  return res.data as BriefTemplate;
};

/** Replace a template's contents (owner only). Null prompt/voice/length clear them. */
export const updateTemplate = async (
  id: string,
  args: TemplatePayload,
): Promise<BriefTemplate> => {
  const res = await axios.put(`${API_BASE_URL}/brief-templates/${id}`, templateBody(args));
  return res.data as BriefTemplate;
};

/** Copy a template the user owns or was given into a new one they own. */
export const copyTemplate = async (id: string): Promise<BriefTemplate> => {
  const res = await axios.post(`${API_BASE_URL}/brief-templates/${id}/copy`);
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

/** Copy a voice profile the user owns or was given into a new one they own. */
export const copyVoiceProfile = async (id: string): Promise<VoiceProfile> => {
  const res = await axios.post(`${API_BASE_URL}/voice-profiles/${id}/copy`);
  return res.data as VoiceProfile;
};

// ---- sharing templates and voice profiles (owner only) ----

/** Which kind of library item a share call is about. */
export type LibraryKind = 'template' | 'voice';

const libraryPath = (kind: LibraryKind): string =>
  kind === 'template' ? 'brief-templates' : 'voice-profiles';

export const listLibraryShares = async (
  kind: LibraryKind,
  id: string,
): Promise<BriefShareTarget[]> => {
  const res = await axios.get(`${API_BASE_URL}/${libraryPath(kind)}/${id}/shares`);
  return expectArray<BriefShareTarget>(res.data, 'shares');
};

/** Share with a user (by email) or a group (by name); returns the updated list. */
export const addLibraryShare = async (
  kind: LibraryKind,
  id: string,
  target: string,
): Promise<BriefShareTarget[]> => {
  const res = await axios.post(`${API_BASE_URL}/${libraryPath(kind)}/${id}/shares`, {
    target,
  });
  return expectArray<BriefShareTarget>(res.data, 'shares');
};

export const removeLibraryShare = async (
  kind: LibraryKind,
  id: string,
  shareId: string,
): Promise<void> => {
  await axios.delete(`${API_BASE_URL}/${libraryPath(kind)}/${id}/shares/${shareId}`);
};
