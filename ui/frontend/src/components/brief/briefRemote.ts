import {
  BRIEF_HISTORY_KEY,
  BRIEF_MIGRATED_KEY,
  BriefListItem,
  RemoteBrief,
  SavedBrief,
} from './briefTypes';
import { createBrief } from './briefCentralApi';

/**
 * Mapping helpers between the server brief models and the local SavedBrief
 * shape the Brief UI already uses, plus the one-time localStorage migration.
 */

// A compact server row as a SavedBrief "stub": everything the history rail
// needs; `sections` stays empty until the full brief is fetched on open.
export const listItemToStub = (item: BriefListItem): SavedBrief => ({
  id: item.id,
  title: item.title,
  query: item.query || '',
  date: Date.parse(item.updated_at) || Date.now(),
  sectionCount: item.section_count,
  sourceCount: item.source_count,
  sections: [],
  voiceId: item.voice_profile_id,
});

// The server stores the full SavedBrief payload as `content`; re-stamp the
// server id so local state and server rows stay keyed identically.
export const remoteToSaved = (remote: RemoteBrief): SavedBrief => ({
  ...remote.content,
  id: remote.id,
  title: remote.title,
  query: remote.query || remote.content.query || '',
  voiceId: remote.voice_profile_id,
});

/**
 * One-time migration: upload any briefs from the user's localStorage bucket to
 * the server, then mark the bucket migrated (per user) so this never repeats.
 * Returns the number of briefs uploaded.
 */
export const migrateLocalBriefs = async (
  userKey: string,
  dataSource: string | null,
): Promise<number> => {
  const migratedKey = `${BRIEF_MIGRATED_KEY}_u_${userKey}`;
  try {
    if (localStorage.getItem(migratedKey)) return 0;
  } catch {
    return 0;
  }
  const bucketKey = `${BRIEF_HISTORY_KEY}_u_${userKey}`;
  let entries: SavedBrief[] = [];
  try {
    const raw = localStorage.getItem(bucketKey);
    entries = raw ? (JSON.parse(raw) as SavedBrief[]) : [];
  } catch {
    entries = [];
  }
  let uploaded = 0;
  for (const entry of entries) {
    if (!entry.sections?.length) continue;
    await createBrief({
      title: entry.title,
      query: entry.query || null,
      dataSource,
      voiceProfileId: entry.voiceId ?? null,
      content: entry,
    });
    uploaded += 1;
  }
  try {
    localStorage.setItem(migratedKey, String(Date.now()));
  } catch {
    /* storage may be unavailable; migration simply reruns next session */
  }
  return uploaded;
};
