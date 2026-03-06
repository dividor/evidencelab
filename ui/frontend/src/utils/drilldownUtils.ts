import type { DrilldownNode, SearchResult } from '../types/api';

/**
 * Serialize a drilldown tree for activity/rating logging.
 * Strips heavy data (results arrays, summaries, prompts) to keep the payload small.
 * Preserves only the tree structure (ids + labels) so admins can see which
 * topics the user explored.
 */
export const serializeDrilldownTree = (
  node: DrilldownNode,
): Record<string, any> => ({
  id: node.id,
  label: node.label,
  children: node.children.map(serializeDrilldownTree),
});

/**
 * Serialize the full drilldown tree for saving research.
 * Preserves all data: summaries, results, prompts, translations.
 */
export const serializeFullDrilldownTree = (
  node: DrilldownNode,
): Record<string, any> => ({
  id: node.id,
  label: node.label,
  summary: node.summary,
  prompt: node.prompt,
  results: node.results,
  translatedText: node.translatedText,
  translatedLang: node.translatedLang,
  expanded: node.expanded,
  children: node.children.map(serializeFullDrilldownTree),
});

/**
 * Return a deep copy of the tree with one node's summary/results patched in.
 * Used before export/save to ensure the currently-viewed node has its live state.
 */
export const patchNodeInTree = (
  node: DrilldownNode,
  targetId: string,
  summary: string,
  nodeResults: SearchResult[]
): DrilldownNode => {
  if (node.id === targetId) {
    return { ...node, summary, results: nodeResults, children: node.children.map((c) => ({ ...c })) };
  }
  return {
    ...node,
    children: node.children.map((c) => patchNodeInTree(c, targetId, summary, nodeResults)),
  };
};
