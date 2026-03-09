import { useMemo, useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactFlow, { Background, Controls, MiniMap, type NodeMouseHandler, BackgroundVariant } from 'reactflow';
import 'reactflow/dist/style.css';
import AppLayout from '@/components/layout/AppLayout';
import CustomGraphNode from '@/components/graph/CustomGraphNode';
import DiagramSwitcher from '@/components/diagram/DiagramSwitcher';
import NodeDetailPanel from '@/components/graph/NodeDetailPanel';
import { usePidStore } from '@/store/usePidStore';
import { getGraph } from '@/lib/api';
import { toReactFlowElements, getConnectedNodes } from '@/lib/graph-utils';
import { Search, Loader2, AlertCircle } from 'lucide-react';
import type { ComponentType, Graph } from '@/types/graph';

const nodeTypes = { custom: CustomGraphNode };
const componentTypes: ComponentType[] = ['pump', 'valve', 'sensor', 'tank', 'pipe', 'compressor'];

const emptyGraph: Graph = { nodes: [], edges: [] };

export default function GraphPage() {
  const { pid_id } = useParams<{ pid_id: string }>();
  const navigate = useNavigate();
  const { currentPidId, graph: storeGraph, validationResults, setPidId, setGraph, selectedNodeId, selectNode, highlightedNodes, setHighlightedNodes, filterType, setFilterType, searchQuery, setSearchQuery } = usePidStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const graph = storeGraph || emptyGraph;

  useEffect(() => {
    if (!pid_id) {
      setLoading(false);
      return;
    }
    if (storeGraph && currentPidId === pid_id) {
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getGraph(pid_id)
      .then((data) => {
        if (!cancelled) {
          setPidId(pid_id);
          setGraph(data);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load graph');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [pid_id, currentPidId, storeGraph, setPidId, setGraph]);

  const filteredGraph = useMemo(() => {
    let nodes = graph.nodes;
    if (filterType) nodes = nodes.filter(n => n.type === filterType);
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      nodes = nodes.filter(n => n.label.toLowerCase().includes(q) || n.type.toLowerCase().includes(q));
    }
    const nodeIds = new Set(nodes.map(n => n.id));
    const edges = graph.edges.filter(e => nodeIds.has(e.source) && nodeIds.has(e.target));
    return { nodes, edges };
  }, [graph, filterType, searchQuery]);

  const { nodes, edges } = useMemo(() => toReactFlowElements(filteredGraph, highlightedNodes), [filteredGraph, highlightedNodes]);

  const selectedNode = useMemo(() => graph.nodes.find(n => n.id === selectedNodeId) || null, [graph, selectedNodeId]);
  const connectedNodes = useMemo(() => {
    if (!selectedNodeId) return [];
    const { upstream, downstream } = getConnectedNodes(graph, selectedNodeId);
    return graph.nodes.filter(n => [...upstream, ...downstream].includes(n.id));
  }, [graph, selectedNodeId]);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    selectNode(node.id);
    const { upstream, downstream } = getConnectedNodes(graph, node.id);
    setHighlightedNodes([node.id, ...upstream, ...downstream]);
  }, [graph, selectNode, setHighlightedNodes]);

  if (!pid_id) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">No P&ID selected. <button type="button" onClick={() => navigate('/')} className="text-primary hover:underline">Go to Dashboard</button></p>
        </div>
      </AppLayout>
    );
  }

  if (loading) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <Loader2 className="h-10 w-10 text-primary animate-spin" />
          <p className="text-sm text-muted-foreground">Loading graph…</p>
        </div>
      </AppLayout>
    );
  }

  if (error) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <AlertCircle className="h-10 w-10 text-destructive" />
          <p className="text-sm text-muted-foreground">{error}</p>
          <button type="button" onClick={() => navigate('/')} className="text-sm text-primary hover:underline">Back to Dashboard</button>
        </div>
      </AppLayout>
    );
  }

  return (
    <AppLayout>
      {/* Floating toolbar */}
      <div className="relative z-20 flex justify-center px-6 pt-3">
        <div className="glass-strong rounded-full px-2 py-1.5 flex items-center gap-1 shadow-lg shadow-black/20">
          <span className="text-[13px] font-semibold text-foreground px-3">Graph</span>
          <span className="text-[10px] text-muted-foreground font-mono bg-white/[0.06] px-2 py-0.5 rounded-full">{pid_id}</span>

          <div className="h-4 w-px bg-white/[0.08] mx-1" />

          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
            <input
              placeholder="Search nodes..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1.5 text-[12px] bg-white/[0.04] border border-white/[0.06] rounded-full w-40 text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-primary/30 transition-all"
            />
          </div>

          <div className="h-4 w-px bg-white/[0.08] mx-1" />

          <div className="flex items-center gap-0.5">
            {['All', ...componentTypes].map(ct => (
              <button
                key={ct}
                onClick={() => setFilterType(ct === 'All' ? null : ct as ComponentType)}
                className={`px-2.5 py-1 rounded-full text-[11px] font-medium capitalize transition-all ${
                  (ct === 'All' && !filterType) || filterType === ct
                    ? 'bg-white/[0.1] text-foreground'
                    : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.05]'
                }`}
              >
                {ct}
              </button>
            ))}
          </div>

          <div className="h-4 w-px bg-white/[0.08] mx-1" />

          <span className="text-[10px] text-muted-foreground font-mono px-2 tabular-nums">
            {filteredGraph.nodes.length}n · {filteredGraph.edges.length}e
          </span>
        </div>
      </div>

      {/* Graph canvas */}
      <div className="flex-1 relative mx-4 mb-10 mt-3 rounded-2xl overflow-hidden glass">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={onNodeClick}
          onPaneClick={() => { selectNode(null); setHighlightedNodes([]); }}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          minZoom={0.3}
          maxZoom={2}
          defaultEdgeOptions={{ type: 'smoothstep' }}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="hsla(228, 12%, 16%, 0.5)" />
          <Controls showInteractive={false} />
          <MiniMap
            nodeColor={(n) => n.data?.color || '#555'}
            maskColor="hsla(228, 14%, 5%, 0.85)"
            style={{ background: 'hsla(228, 14%, 8%, 0.7)' }}
          />
        </ReactFlow>
        <NodeDetailPanel
          node={selectedNode}
          connectedNodes={connectedNodes}
          onClose={() => { selectNode(null); setHighlightedNodes([]); }}
        />
      </div>
      {validationResults.length > 1 && (
        <div className="px-4 pb-4">
          <div className="flex justify-center">
            <div className="glass-strong rounded-full px-2 py-1.5">
              <DiagramSwitcher results={validationResults} currentPidId={pid_id} basePath="/graph" />
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
