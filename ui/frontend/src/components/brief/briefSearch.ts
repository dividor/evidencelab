import { BriefListItem } from './briefTypes';

/**
 * Filter briefs by the words typed into the library search: a brief matches
 * when its name or its owner's name or email contains every word typed,
 * ignoring case. An empty search matches everything.
 */
export const filterBriefs = (briefs: BriefListItem[], search: string, includeOwner = true): BriefListItem[] => {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return briefs;
  return briefs.filter((b) => {
    const fields = includeOwner ? [b.title, b.owner_name, b.owner_email] : [b.title];
    const haystack = fields.filter(Boolean).join(' ').toLowerCase();
    return words.every((w) => haystack.includes(w));
  });
};
