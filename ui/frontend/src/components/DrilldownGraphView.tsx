import React from 'react';
import { DrilldownNode } from '../types/api';

interface DrilldownGraphViewProps {
  tree: DrilldownNode;
  activeNodeId: string;
  onNodeClick: (nodeId: string) => void;
}

interface FlatNode {
  id: string;
  label: string;
  depth: number;
  isActive: boolean;
  isRoot: boolean;
  parentIndex: number | null;
}

const NODE_RADIUS = 8;
const NODE_GAP_Y = 56;
const DEPTH_INDENT = 28;
const PADDING_TOP = 20;
const PADDING_LEFT = 16;

/** Flatten tree into a list with depth info using DFS */
const flattenTree = (
  node: DrilldownNode,
  activeNodeId: string,
  depth: number,
  parentIndex: number | null,
  result: FlatNode[]
): void => {
  const index = result.length;
  result.push({
    id: node.id,
    label: node.label,
    depth,
    isActive: node.id === activeNodeId,
    isRoot: depth === 0,
    parentIndex,
  });
  for (const child of node.children) {
    flattenTree(child, activeNodeId, depth + 1, index, result);
  }
};

export const DrilldownGraphView: React.FC<DrilldownGraphViewProps> = ({
  tree,
  activeNodeId,
  onNodeClick,
}) => {
  const flatNodes: FlatNode[] = [];
  flattenTree(tree, activeNodeId, 0, null, flatNodes);

  if (flatNodes.length === 0) return null;

  const svgHeight = PADDING_TOP + flatNodes.length * NODE_GAP_Y + 12;

  return (
    <div className="drilldown-graph-view">
      <svg
        width="100%"
        height={svgHeight}
        className="drilldown-graph-svg"
      >
        {flatNodes.map((node, i) => {
          const nodeX = PADDING_LEFT + NODE_RADIUS + node.depth * DEPTH_INDENT;
          const y = PADDING_TOP + i * NODE_GAP_Y;

          return (
            <g key={node.id}>
              {/* Connector line to parent */}
              {node.parentIndex !== null && (
                <polyline
                  points={[
                    `${PADDING_LEFT + NODE_RADIUS + (node.depth - 1) * DEPTH_INDENT},${PADDING_TOP + node.parentIndex * NODE_GAP_Y + NODE_RADIUS}`,
                    `${PADDING_LEFT + NODE_RADIUS + (node.depth - 1) * DEPTH_INDENT},${y}`,
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
                className={`drilldown-graph-node ${node.isActive ? 'active' : ''} ${node.isRoot ? 'root' : ''}`}
                onClick={() => onNodeClick(node.id)}
              />
              {/* Label */}
              <foreignObject
                x={nodeX + NODE_RADIUS + 10}
                y={y - 12}
                width="calc(100% - 80px)"
                height={NODE_GAP_Y}
              >
                <div
                  className={`drilldown-graph-label ${node.isActive ? 'active' : ''} ${node.isRoot ? 'root' : ''}`}
                  onClick={() => onNodeClick(node.id)}
                >
                  {node.label}
                </div>
              </foreignObject>
            </g>
          );
        })}
      </svg>
    </div>
  );
};
