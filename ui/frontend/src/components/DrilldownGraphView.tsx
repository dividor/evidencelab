import React, { useState, useRef, useEffect } from 'react';
import { DrilldownNode } from '../types/api';

interface DrilldownGraphViewProps {
  tree: DrilldownNode;
  activeNodeId: string;
  onNodeClick: (nodeId: string) => void;
  onAddChild?: (parentId: string) => void;
  onRemoveNode?: (nodeId: string) => void;
  addingNodeParentId?: string | null;
  onAddNodeSubmit?: (parentId: string, query: string) => void;
  onAddNodeCancel?: () => void;
}

interface FlatEntry {
  type: 'node' | 'add-row';
  id: string;
  label: string;
  depth: number;
  isActive: boolean;
  isRoot: boolean;
  isLoading: boolean;
  parentIndex: number | null;
  parentId: string;
}

const NODE_RADIUS = 8;
const NODE_GAP_Y = 56;
const DEPTH_INDENT = 28;
const PADDING_TOP = 20;
const PADDING_LEFT = 16;

/** Flatten tree into a list with depth info using DFS, inserting add-rows after children */
const flattenTree = (
  node: DrilldownNode,
  activeNodeId: string,
  depth: number,
  parentIndex: number | null,
  result: FlatEntry[],
  addingParentId?: string | null,
): void => {
  const index = result.length;
  result.push({
    type: 'node',
    id: node.id,
    label: node.label,
    depth,
    isActive: node.id === activeNodeId,
    isRoot: depth === 0,
    isLoading: node.summary === 'Researching...',
    parentIndex,
    parentId: '',
  });
  for (const child of node.children) {
    flattenTree(child, activeNodeId, depth + 1, index, result, addingParentId);
  }
  // Show add-row after children if node has children or user is adding to this node
  if (node.children.length > 0 || addingParentId === node.id) {
    result.push({
      type: 'add-row',
      id: `add-${node.id}`,
      label: '+ Add topic',
      depth: depth + 1,
      isActive: false,
      isRoot: false,
      isLoading: false,
      parentIndex: index,
      parentId: node.id,
    });
  }
};

export const DrilldownGraphView: React.FC<DrilldownGraphViewProps> = ({
  tree,
  activeNodeId,
  onNodeClick,
  onAddChild,
  onRemoveNode,
  addingNodeParentId,
  onAddNodeSubmit,
  onAddNodeCancel,
}) => {
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (addingNodeParentId) {
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [addingNodeParentId]);

  useEffect(() => {
    setInputValue('');
  }, [addingNodeParentId]);

  const flatEntries: FlatEntry[] = [];
  flattenTree(tree, activeNodeId, 0, null, flatEntries, addingNodeParentId);

  if (flatEntries.length === 0) return null;

  const svgHeight = PADDING_TOP + flatEntries.length * NODE_GAP_Y + 12;

  const handleInputKeyDown = (e: React.KeyboardEvent, parentId: string) => {
    if (e.key === 'Enter' && inputValue.trim()) {
      onAddNodeSubmit?.(parentId, inputValue.trim());
      setInputValue('');
    } else if (e.key === 'Escape') {
      onAddNodeCancel?.();
      setInputValue('');
    }
  };

  const handleInputBlur = (parentId: string) => {
    if (inputValue.trim()) {
      onAddNodeSubmit?.(parentId, inputValue.trim());
    } else {
      onAddNodeCancel?.();
    }
    setInputValue('');
  };

  return (
    <div className="drilldown-graph-view">
      <svg
        width="100%"
        height={svgHeight}
        className="drilldown-graph-svg"
      >
        {flatEntries.map((entry, i) => {
          const nodeX = PADDING_LEFT + NODE_RADIUS + entry.depth * DEPTH_INDENT;
          const y = PADDING_TOP + i * NODE_GAP_Y;

          if (entry.type === 'add-row') {
            const isAdding = addingNodeParentId === entry.parentId;
            return (
              <g key={entry.id}>
                {entry.parentIndex !== null && (
                  <polyline
                    points={[
                      `${PADDING_LEFT + NODE_RADIUS + (entry.depth - 1) * DEPTH_INDENT},${PADDING_TOP + entry.parentIndex * NODE_GAP_Y + NODE_RADIUS}`,
                      `${PADDING_LEFT + NODE_RADIUS + (entry.depth - 1) * DEPTH_INDENT},${y}`,
                      `${nodeX - NODE_RADIUS},${y}`,
                    ].join(' ')}
                    className="drilldown-graph-edge"
                    fill="none"
                  />
                )}
                <circle
                  cx={nodeX}
                  cy={y}
                  r={NODE_RADIUS}
                  className="drilldown-graph-node add-node"
                  onClick={() => !isAdding && onAddChild?.(entry.parentId)}
                />
                <foreignObject
                  x={nodeX + NODE_RADIUS + 10}
                  y={y - NODE_RADIUS - 2}
                  width="calc(100% - 80px)"
                  height={NODE_GAP_Y}
                >
                  {isAdding ? (
                    <input
                      ref={inputRef}
                      className="drilldown-add-input"
                      type="text"
                      value={inputValue}
                      onChange={(e) => setInputValue(e.target.value)}
                      onKeyDown={(e) => handleInputKeyDown(e, entry.parentId)}
                      onBlur={() => handleInputBlur(entry.parentId)}
                      placeholder="Enter your research query"
                    />
                  ) : (
                    <div
                      className="drilldown-add-node"
                      onClick={() => onAddChild?.(entry.parentId)}
                    >
                      + Add topic
                    </div>
                  )}
                </foreignObject>
              </g>
            );
          }

          return (
            <g key={entry.id}>
              {/* Connector line to parent */}
              {entry.parentIndex !== null && (
                <polyline
                  points={[
                    `${PADDING_LEFT + NODE_RADIUS + (entry.depth - 1) * DEPTH_INDENT},${PADDING_TOP + entry.parentIndex * NODE_GAP_Y + NODE_RADIUS}`,
                    `${PADDING_LEFT + NODE_RADIUS + (entry.depth - 1) * DEPTH_INDENT},${y}`,
                    `${nodeX - NODE_RADIUS},${y}`,
                  ].join(' ')}
                  className="drilldown-graph-edge"
                  fill="none"
                />
              )}
              {/* Node circle */}
              <circle
                cx={nodeX}
                cy={y}
                r={NODE_RADIUS}
                className={`drilldown-graph-node ${entry.isActive ? 'active' : ''} ${entry.isRoot ? 'root' : ''} ${entry.isLoading ? 'loading' : ''}`}
                onClick={() => onNodeClick(entry.id)}
              />
              {/* Label + action buttons */}
              <foreignObject
                x={nodeX + NODE_RADIUS + 10}
                y={y - 12}
                width="calc(100% - 80px)"
                height={NODE_GAP_Y}
              >
                <div className="drilldown-graph-label-row">
                  <div
                    className={`drilldown-graph-label ${entry.isActive ? 'active' : ''} ${entry.isRoot ? 'root' : ''} ${entry.isLoading ? 'loading' : ''}`}
                    onClick={() => onNodeClick(entry.id)}
                  >
                    {entry.label}
                    {entry.isLoading && <span className="drilldown-loading-indicator"> Researching...</span>}
                  </div>
                  {(onAddChild || onRemoveNode) && (
                    <span className="drilldown-graph-actions">
                      {onAddChild && (
                        <button
                          className="drilldown-node-btn add"
                          onClick={(e) => { e.stopPropagation(); onAddChild(entry.id); }}
                          title="Add child topic"
                          type="button"
                        >
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M5 1.5V8.5M1.5 5H8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                          </svg>
                        </button>
                      )}
                      {onRemoveNode && !entry.isRoot && (
                        <button
                          className="drilldown-node-btn remove"
                          onClick={(e) => { e.stopPropagation(); onRemoveNode(entry.id); }}
                          title="Remove topic"
                          type="button"
                        >
                          <svg width="10" height="10" viewBox="0 0 10 10" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M1.5 5H8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                          </svg>
                        </button>
                      )}
                    </span>
                  )}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
};
