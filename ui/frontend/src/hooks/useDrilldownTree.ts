import { useState, useRef, useCallback } from 'react';
import { DrilldownNode, SearchResult } from '../types/api';

/** Snapshot of the AI summary UI state needed for save/restore */
export interface AiSummarySnapshot {
  summary: string;
  prompt: string;
  results: SearchResult[];
  expanded: boolean;
  translatedText: string | null;
  translatedLang: string | null;
}

interface UseDrilldownTreeResult {
  drilldownTree: DrilldownNode | null;
  currentNodeId: string | null;
  isDrilldown: boolean;
  currentHighlight: string | undefined;
  resetTree: () => void;
  loadTree: (tree: DrilldownNode) => void;
  startDrilldown: (highlightedText: string, snapshot: AiSummarySnapshot, rootLabel?: string) => string;
  addChildNode: (label: string, snapshot: AiSummarySnapshot, rootLabel?: string) => string;
  addChildToNode: (parentId: string, label: string) => string;
  removeNode: (nodeId: string) => void;
  getNode: (nodeId: string) => DrilldownNode | null;
  updateNodeData: (nodeId: string, data: Partial<AiSummarySnapshot>) => void;
  navigateBack: (snapshot: AiSummarySnapshot) => DrilldownNode | null;
  navigateToNode: (nodeId: string, snapshot: AiSummarySnapshot) => DrilldownNode | null;
}

/** Find a node by ID in the drilldown tree */
const findNode = (node: DrilldownNode | null, id: string): DrilldownNode | null => {
  if (!node) return null;
  if (node.id === id) return node;
  for (const child of node.children) {
    const found = findNode(child, id);
    if (found) return found;
  }
  return null;
};

/** Find the parent of a node by ID */
const findParent = (node: DrilldownNode | null, id: string): DrilldownNode | null => {
  if (!node) return null;
  for (const child of node.children) {
    if (child.id === id) return node;
    const found = findParent(child, id);
    if (found) return found;
  }
  return null;
};

/** Deep-clone and update a node in the tree */
const updateNodeInTree = (
  root: DrilldownNode,
  targetId: string,
  updater: (node: DrilldownNode) => DrilldownNode
): DrilldownNode => {
  if (root.id === targetId) return updater({ ...root });
  return {
    ...root,
    children: root.children.map((child) => updateNodeInTree(child, targetId, updater)),
  };
};

/** Save a snapshot into the tree at the given node */
const saveSnapshot = (
  tree: DrilldownNode,
  nodeId: string,
  snapshot: AiSummarySnapshot
): DrilldownNode =>
  updateNodeInTree(tree, nodeId, (node) => ({
    ...node,
    summary: snapshot.summary,
    prompt: snapshot.prompt,
    results: snapshot.results,
    expanded: snapshot.expanded,
    translatedText: snapshot.translatedText,
    translatedLang: snapshot.translatedLang,
  }));

/** Extract the maximum numeric ID from the tree to reset the counter after load */
const getMaxIdCounter = (node: DrilldownNode): number => {
  let max = 0;
  const match = node.id.match(/^dd-(\d+)$/);
  if (match) max = parseInt(match[1], 10);
  for (const child of node.children) {
    max = Math.max(max, getMaxIdCounter(child));
  }
  return max;
};

export const useDrilldownTree = (): UseDrilldownTreeResult => {
  const [drilldownTree, setDrilldownTree] = useState<DrilldownNode | null>(null);
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const idCounter = useRef(0);

  const isDrilldown = currentNodeId !== null;
  const currentHighlight = drilldownTree && currentNodeId
    ? findNode(drilldownTree, currentNodeId)?.label
    : undefined;

  const resetTree = useCallback(() => {
    setDrilldownTree(null);
    setCurrentNodeId(null);
  }, []);

  /** Load a complete drilldown tree (e.g., from saved research) */
  const loadTree = useCallback((tree: DrilldownNode) => {
    setDrilldownTree(tree);
    setCurrentNodeId(null); // Start at root
    idCounter.current = getMaxIdCounter(tree);
  }, []);

  /**
   * Start a drilldown from the current node.
   * Returns the new child node ID so the caller can stream into it.
   */
  const startDrilldown = useCallback((
    highlightedText: string,
    snapshot: AiSummarySnapshot,
    rootLabel?: string
  ): string => {
    const newId = `dd-${++idCounter.current}`;
    const childStub: DrilldownNode = {
      id: newId,
      label: highlightedText,
      summary: '',
      prompt: '',
      results: snapshot.results,
      translatedText: null,
      translatedLang: null,
      expanded: false,
      children: [],
    };

    setDrilldownTree((prev) => {
      if (!prev) {
        // First drilldown: create root from current state + child
        return {
          id: 'root',
          label: rootLabel || '',
          ...snapshot,
          children: [childStub],
        } as DrilldownNode;
      }
      // Save current state, then add child
      const targetId = currentNodeId || 'root';
      const saved = saveSnapshot(prev, targetId, snapshot);
      return updateNodeInTree(saved, targetId, (node) => ({
        ...node,
        children: [...node.children, childStub],
      }));
    });

    setCurrentNodeId(newId);
    return newId;
  }, [currentNodeId]);

  /**
   * Navigate back to the parent node.
   * Returns the parent node so the caller can restore UI state, or null.
   */
  const navigateBack = useCallback((
    snapshot: AiSummarySnapshot
  ): DrilldownNode | null => {
    if (!drilldownTree || !currentNodeId) return null;

    // Save current state
    const targetId = currentNodeId;
    setDrilldownTree((prev) =>
      prev ? saveSnapshot(prev, targetId, snapshot) : prev
    );

    const parent = findParent(drilldownTree, currentNodeId);
    if (parent) {
      setCurrentNodeId(parent.id === 'root' ? null : parent.id);
    }
    return parent;
  }, [drilldownTree, currentNodeId]);

  /**
   * Navigate to any node by ID.
   * Returns the target node so the caller can restore UI state, or null.
   */
  const navigateToNode = useCallback((
    nodeId: string,
    snapshot: AiSummarySnapshot
  ): DrilldownNode | null => {
    if (!drilldownTree) return null;
    const effectiveCurrentId = currentNodeId || 'root';
    if (nodeId === effectiveCurrentId) return null;

    // Save current state
    setDrilldownTree((prev) =>
      prev ? saveSnapshot(prev, effectiveCurrentId, snapshot) : prev
    );

    const target = findNode(drilldownTree, nodeId);
    if (target) {
      setCurrentNodeId(nodeId === 'root' ? null : nodeId);
    }
    return target;
  }, [drilldownTree, currentNodeId]);

  /**
   * Add a child node without navigating to it.
   * Returns the new child node ID.
   */
  const addChildNode = useCallback((
    label: string,
    snapshot: AiSummarySnapshot,
    rootLabel?: string
  ): string => {
    const newId = `dd-${++idCounter.current}`;
    const childStub: DrilldownNode = {
      id: newId,
      label,
      summary: '',
      prompt: '',
      results: [],
      translatedText: null,
      translatedLang: null,
      expanded: false,
      children: [],
    };

    setDrilldownTree((prev) => {
      if (!prev) {
        return {
          id: 'root',
          label: rootLabel || '',
          ...snapshot,
          children: [childStub],
        } as DrilldownNode;
      }
      const targetId = currentNodeId || 'root';
      const saved = saveSnapshot(prev, targetId, snapshot);
      return updateNodeInTree(saved, targetId, (node) => ({
        ...node,
        children: [...node.children, childStub],
      }));
    });

    return newId;
  }, [currentNodeId]);

  /**
   * Add a child node to a specific parent (by ID) without navigating.
   * Unlike addChildNode, this does not save a snapshot or require current-node context.
   * Returns the new child node ID.
   */
  const addChildToNode = useCallback((
    parentId: string,
    label: string,
  ): string => {
    const newId = `dd-${++idCounter.current}`;
    const childStub: DrilldownNode = {
      id: newId,
      label,
      summary: '',
      prompt: '',
      results: [],
      translatedText: null,
      translatedLang: null,
      expanded: false,
      children: [],
    };
    setDrilldownTree((prev) => {
      if (!prev) return prev;
      return updateNodeInTree(prev, parentId, (node) => ({
        ...node,
        children: [...node.children, childStub],
      }));
    });
    return newId;
  }, []);

  /** Remove a node (and its subtree) from the tree. Cannot remove root. */
  const removeNode = useCallback((nodeId: string): void => {
    if (nodeId === 'root') return;
    setDrilldownTree((prev) => {
      if (!prev) return prev;
      const removeFromChildren = (node: DrilldownNode): DrilldownNode => ({
        ...node,
        children: node.children
          .filter((c) => c.id !== nodeId)
          .map(removeFromChildren),
      });
      return removeFromChildren(prev);
    });
    // If the removed node was the current node, navigate to root
    if (currentNodeId === nodeId) {
      setCurrentNodeId(null);
    }
  }, [currentNodeId]);

  /** Look up a node by ID (read-only) */
  const getNode = useCallback((nodeId: string): DrilldownNode | null => {
    return findNode(drilldownTree, nodeId);
  }, [drilldownTree]);

  /** Update a node's data (summary, results, etc.) without navigating */
  const updateNodeData = useCallback((
    nodeId: string,
    data: Partial<AiSummarySnapshot>
  ): void => {
    setDrilldownTree((prev) => {
      if (!prev) return prev;
      return updateNodeInTree(prev, nodeId, (node) => ({ ...node, ...data }));
    });
  }, []);

  return {
    drilldownTree,
    currentNodeId,
    isDrilldown,
    currentHighlight,
    resetTree,
    loadTree,
    startDrilldown,
    addChildNode,
    addChildToNode,
    removeNode,
    getNode,
    updateNodeData,
    navigateBack,
    navigateToNode,
  };
};
