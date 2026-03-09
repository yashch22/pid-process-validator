import { type Node, type Edge, MarkerType } from 'reactflow';
import type { Graph, ComponentType } from '@/types/graph';

export const NODE_COLORS: Record<ComponentType, string> = {
  pump: 'hsl(217, 91%, 60%)',
  valve: 'hsl(142, 70%, 45%)',
  sensor: 'hsl(262, 83%, 58%)',
  tank: 'hsl(25, 95%, 53%)',
  pipe: 'hsl(220, 10%, 60%)',
  compressor: 'hsl(340, 75%, 55%)',
};

export const NODE_ICONS: Record<ComponentType, string> = {
  pump: '⟳',
  valve: '◇',
  sensor: '◉',
  tank: '▭',
  pipe: '─',
  compressor: '⊛',
};

export function toReactFlowElements(graph: Graph, highlightedNodes: string[] = []) {
  const cols = 3;
  const xGap = 280;
  const yGap = 160;

  const nodes: Node[] = graph.nodes.map((n, i) => ({
    id: n.id,
    type: 'custom',
    position: { x: (i % cols) * xGap + 50, y: Math.floor(i / cols) * yGap + 50 },
    data: {
      ...n,
      color: NODE_COLORS[n.type] || NODE_COLORS.pipe,
      icon: NODE_ICONS[n.type] || '●',
      highlighted: highlightedNodes.includes(n.id),
    },
  }));

  const edges: Edge[] = graph.edges.map((e, i) => ({
    id: `e-${i}`,
    source: e.source,
    target: e.target,
    animated: highlightedNodes.includes(e.source) && highlightedNodes.includes(e.target),
    style: {
      stroke: highlightedNodes.includes(e.source) && highlightedNodes.includes(e.target)
        ? 'hsl(0, 72%, 51%)'
        : 'hsl(220, 10%, 60%)',
      strokeWidth: 2,
    },
    markerEnd: { type: MarkerType.ArrowClosed },
  }));

  return { nodes, edges };
}

export function getConnectedNodes(graph: Graph, nodeId: string): { upstream: string[]; downstream: string[] } {
  const upstream: string[] = [];
  const downstream: string[] = [];

  const visit = (id: string, direction: 'up' | 'down', visited: Set<string>) => {
    if (visited.has(id)) return;
    visited.add(id);
    if (direction === 'up') {
      graph.edges.filter(e => e.target === id).forEach(e => {
        upstream.push(e.source);
        visit(e.source, 'up', visited);
      });
    } else {
      graph.edges.filter(e => e.source === id).forEach(e => {
        downstream.push(e.target);
        visit(e.target, 'down', visited);
      });
    }
  };

  visit(nodeId, 'up', new Set());
  visit(nodeId, 'down', new Set());
  return { upstream, downstream };
}
