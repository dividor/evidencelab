import type { DrilldownNode } from '../types/api';

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
