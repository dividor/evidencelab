import { useCallback, useEffect, useState } from 'react';
import {
  TemplatePayload,
  copyBrief as copyBriefRemote,
  copyTemplate as copyTemplateRemote,
  copyVoiceProfile,
  createTemplate,
  createVoiceProfile,
  deleteBriefRemote,
  deleteTemplate,
  deleteVoiceProfile,
  listAllBriefs,
  listMyBriefs,
  listSharedBriefs,
  listTemplates,
  listVoiceProfiles,
  updateTemplate,
  updateVoiceProfile,
} from './briefCentralApi';
import { BriefListItem, BriefTemplate, VoiceProfile } from './briefTypes';

// 'all' is the administrators' view of every brief in the system.
export type CentralTab = 'mine' | 'shared' | 'templates' | 'voices' | 'all';

const errMessage = (e: unknown, fallback: string): string =>
  e instanceof Error ? e.message : fallback;

// Lists hold the user's own items first, then items shared with them (the
// server's order); a new item of the user's own goes at the end of their part.
const insertOwned = <T extends { can_edit: boolean }>(list: T[], item: T): T[] => {
  const firstShared = list.findIndex((x) => !x.can_edit);
  if (firstShared < 0) return [...list, item];
  return [...list.slice(0, firstShared), item, ...list.slice(firstShared)];
};

/**
 * State for the Brief Central landing page: the user's briefs, briefs shared
 * with them, and the templates and voice & tone profiles they own or were
 * given — all server-backed. Only used when the user module is enabled and a
 * user is logged in.
 */
export const useBriefCentral = (enabled: boolean, isAdmin = false) => {
  const [tab, setTab] = useState<CentralTab>('mine');
  const [myBriefs, setMyBriefs] = useState<BriefListItem[]>([]);
  const [sharedBriefs, setSharedBriefs] = useState<BriefListItem[]>([]);
  const [templates, setTemplates] = useState<BriefTemplate[]>([]);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [allBriefs, setAllBriefs] = useState<BriefListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const [mine, shared, tpls, vps, all] = await Promise.all([
        listMyBriefs(),
        listSharedBriefs(),
        listTemplates(),
        listVoiceProfiles(),
        isAdmin ? listAllBriefs() : Promise.resolve([] as BriefListItem[]),
      ]);
      setMyBriefs(mine);
      setSharedBriefs(shared);
      setTemplates(tpls);
      setVoices(vps);
      setAllBriefs(all);
    } catch (e) {
      setError(errMessage(e, 'Could not load your briefs.'));
    } finally {
      setLoading(false);
    }
  }, [enabled, isAdmin]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const removeBrief = useCallback(async (id: string) => {
    await deleteBriefRemote(id);
    setMyBriefs((prev) => prev.filter((b) => b.id !== id));
  }, []);

  // Copy a brief into the user's own (admins: any brief); it appears under
  // Saved Briefs.
  const copyBrief = useCallback(async (id: string) => {
    const created = await copyBriefRemote(id);
    setMyBriefs(await listMyBriefs());
    return created;
  }, []);

  // Create a template, or update one the user owns when `id` is given.
  const saveTemplate = useCallback(async (id: string | null, args: TemplatePayload) => {
    if (id) {
      const updated = await updateTemplate(id, args);
      setTemplates((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      return updated;
    }
    const created = await createTemplate(args);
    setTemplates((prev) => [created, ...prev]);
    return created;
  }, []);

  // Copy a template the user owns or was given; the copy is theirs to edit.
  const copyTemplate = useCallback(async (id: string) => {
    const created = await copyTemplateRemote(id);
    setTemplates((prev) => [created, ...prev]);
    return created;
  }, []);

  // A template's or voice's share count changed in the Share dialog.
  const setTemplateShareCount = useCallback((id: string, count: number) => {
    setTemplates((prev) => prev.map((t) => (t.id === id ? { ...t, share_count: count } : t)));
  }, []);
  const setVoiceShareCount = useCallback((id: string, count: number) => {
    setVoices((prev) => prev.map((v) => (v.id === id ? { ...v, share_count: count } : v)));
  }, []);

  const removeTemplate = useCallback(async (id: string) => {
    await deleteTemplate(id);
    setTemplates((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const saveVoice = useCallback(
    async (args: {
      id: string | null;
      name: string;
      description: string | null;
      instructions: string;
    }) => {
      if (args.id) {
        const updated = await updateVoiceProfile(args.id, {
          name: args.name,
          description: args.description,
          instructions: args.instructions,
        });
        setVoices((prev) => prev.map((v) => (v.id === updated.id ? updated : v)));
        return updated;
      }
      const created = await createVoiceProfile({
        name: args.name,
        description: args.description,
        instructions: args.instructions,
      });
      setVoices((prev) => insertOwned(prev, created));
      return created;
    },
    [],
  );

  const removeVoice = useCallback(async (id: string) => {
    await deleteVoiceProfile(id);
    setVoices((prev) => prev.filter((v) => v.id !== id));
  }, []);

  // Sharing a template also shares the voices it uses, so their share counts
  // change; reload the voices without the page-wide loading state.
  const refreshVoices = useCallback(async () => {
    try {
      setVoices(await listVoiceProfiles());
    } catch (e) {
      setError(errMessage(e, 'Could not reload voice & tone profiles.'));
    }
  }, []);

  const copyVoice = useCallback(async (id: string) => {
    const created = await copyVoiceProfile(id);
    setVoices((prev) => insertOwned(prev, created));
    return created;
  }, []);

  const voiceById = useCallback(
    (id: string | null | undefined): VoiceProfile | null =>
      (id && voices.find((v) => v.id === id)) || null,
    [voices],
  );

  return {
    tab,
    setTab,
    myBriefs,
    sharedBriefs,
    templates,
    voices,
    allBriefs,
    isAdmin,
    loading,
    error,
    setError,
    refresh,
    removeBrief,
    copyBrief,
    saveTemplate,
    copyTemplate,
    removeTemplate,
    setTemplateShareCount,
    saveVoice,
    copyVoice,
    removeVoice,
    setVoiceShareCount,
    refreshVoices,
    voiceById,
  };
};

export type UseBriefCentralReturn = ReturnType<typeof useBriefCentral>;
