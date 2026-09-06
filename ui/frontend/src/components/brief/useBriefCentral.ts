import { useCallback, useEffect, useState } from 'react';
import {
  createTemplate,
  createVoiceProfile,
  deleteBriefRemote,
  deleteTemplate,
  deleteVoiceProfile,
  listMyBriefs,
  listSharedBriefs,
  listTemplates,
  listVoiceProfiles,
  updateVoiceProfile,
} from './briefCentralApi';
import {
  BriefListItem,
  BriefTemplate,
  BriefTemplateHeading,
  VoiceProfile,
} from './briefTypes';

export type CentralTab = 'mine' | 'shared' | 'templates' | 'voices';

const errMessage = (e: unknown, fallback: string): string =>
  e instanceof Error ? e.message : fallback;

/**
 * State for the Brief Central landing page: the user's briefs, briefs shared
 * with them, their templates and voice & tone profiles — all server-backed.
 * Only used when the user module is enabled and a user is logged in.
 */
export const useBriefCentral = (enabled: boolean) => {
  const [tab, setTab] = useState<CentralTab>('mine');
  const [myBriefs, setMyBriefs] = useState<BriefListItem[]>([]);
  const [sharedBriefs, setSharedBriefs] = useState<BriefListItem[]>([]);
  const [templates, setTemplates] = useState<BriefTemplate[]>([]);
  const [voices, setVoices] = useState<VoiceProfile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    try {
      const [mine, shared, tpls, vps] = await Promise.all([
        listMyBriefs(),
        listSharedBriefs(),
        listTemplates(),
        listVoiceProfiles(),
      ]);
      setMyBriefs(mine);
      setSharedBriefs(shared);
      setTemplates(tpls);
      setVoices(vps);
    } catch (e) {
      setError(errMessage(e, 'Could not load your briefs.'));
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const removeBrief = useCallback(async (id: string) => {
    await deleteBriefRemote(id);
    setMyBriefs((prev) => prev.filter((b) => b.id !== id));
  }, []);

  const saveTemplate = useCallback(
    async (args: {
      name: string;
      description: string | null;
      headings: BriefTemplateHeading[];
      withText: boolean;
    }) => {
      const created = await createTemplate(args);
      setTemplates((prev) => [created, ...prev]);
      return created;
    },
    [],
  );

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
      setVoices((prev) => [...prev, created]);
      return created;
    },
    [],
  );

  const removeVoice = useCallback(async (id: string) => {
    await deleteVoiceProfile(id);
    setVoices((prev) => prev.filter((v) => v.id !== id));
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
    loading,
    error,
    setError,
    refresh,
    removeBrief,
    saveTemplate,
    removeTemplate,
    saveVoice,
    removeVoice,
    voiceById,
  };
};

export type UseBriefCentralReturn = ReturnType<typeof useBriefCentral>;
