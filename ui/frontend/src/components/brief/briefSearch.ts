import { BriefListItem } from './briefTypes';

/**
 * Filter briefs by a search typed in the admin All Briefs tab: a brief matches
 * when its name or its owner's name or email contains every word typed,
 * ignoring case. An empty search matches everything.
 */
export const filterBriefs = (briefs: BriefListItem[], search: string): BriefListItem[] => {
  const words = search.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return briefs;
  return briefs.filter((b) => {
    const haystack = [b.title, b.owner_name, b.owner_email].filter(Boolean).join(' ').toLowerCase();
    return words.every((w) => haystack.includes(w));
  });
};
