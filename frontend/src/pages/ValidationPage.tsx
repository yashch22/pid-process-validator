import { useMemo, useCallback, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import ReactFlow, { Background, Controls, BackgroundVariant } from 'reactflow';
import 'reactflow/dist/style.css';
import AppLayout from '@/components/layout/AppLayout';
import CustomGraphNode from '@/components/graph/CustomGraphNode';
import DiagramSwitcher from '@/components/diagram/DiagramSwitcher';
import { usePidStore } from '@/store/usePidStore';
import { getGraph, getValidation, getValidationBySop } from '@/lib/api';
import { toReactFlowElements, NODE_COLORS } from '@/lib/graph-utils';
import type { ValidationIssue, Graph, ValidationResult } from '@/types/graph';
import { Loader2, AlertCircle } from 'lucide-react';

const nodeTypes = { custom: CustomGraphNode };
const severityDot = { error: 'bg-destructive', warning: 'bg-warning', info: 'bg-info' };

const emptyGraph: Graph = { nodes: [], edges: [] };
const emptyValidation: ValidationResult = { status: 'pending', issues: [] };

export default function ValidationPage() {
  const { pid_id, sop_id } = useParams<{ pid_id?: string; sop_id?: string }>();
  const navigate = useNavigate();
  const { currentPidId, graph: storeGraph, validation: storeValidation, validationResults, setPidId, setGraph, setValidation, setValidationResults, selectedIssueIndex, selectIssue, highlightedNodes, setHighlightedNodes } = usePidStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sopFileName, setSopFileName] = useState<string | null>(null);

  const graph = storeGraph || emptyGraph;
  const validation = storeValidation || emptyValidation;

  useEffect(() => {
    if (!pid_id && !sop_id) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    if (sop_id) {
      getValidationBySop(sop_id)
        .then(({ results, sop_file_name }) => {
          if (!cancelled) setSopFileName(sop_file_name ?? null);
          if (!cancelled && results.length > 0) {
            setValidationResults(results);
            const first = results[0];
            setPidId(first.pid_id);
            return Promise.all([getGraph(first.pid_id), Promise.resolve({ status: first.status, issues: first.issues ?? [] })])
              .then(([graphData, validationData]) => {
                if (!cancelled) {
                  setGraph(graphData);
                  setValidation(validationData);
                }
              });
          } else if (!cancelled && results.length === 0) {
            setValidationResults([]);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load validation');
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    } else if (pid_id) {
      if (storeGraph && storeValidation && currentPidId === pid_id) {
        setLoading(false);
        setError(null);
        return;
      }
      Promise.all([getGraph(pid_id), getValidation(pid_id)])
        .then(([graphData, validationData]) => {
          if (!cancelled) {
            setPidId(pid_id);
            setGraph(graphData);
            setValidation(validationData);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load validation');
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }
    return () => { cancelled = true; };
  }, [pid_id, sop_id, currentPidId, storeGraph, storeValidation, setPidId, setGraph, setValidation, setValidationResults]);

  const { nodes, edges } = useMemo(() => toReactFlowElements(graph, highlightedNodes), [graph, highlightedNodes]);

  const handleIssueClick = useCallback((issue: ValidationIssue, index: number) => {
    selectIssue(index);
    setHighlightedNodes(issue.relatedNodes || []);
  }, [selectIssue, setHighlightedNodes]);

  const selectedIssue = selectedIssueIndex !== null ? validation.issues[selectedIssueIndex] : null;

  const displayPidId = pid_id ?? currentPidId;

  if (!pid_id && !sop_id) {
    return (
      <AppLayout>
        <div className="flex-1 flex items-center justify-center">
          <p className="text-muted-foreground">No P&ID or SOP selected. <button type="button" onClick={() => navigate('/')} className="text-primary hover:underline">Go to Dashboard</button></p>
        </div>
      </AppLayout>
    );
  }

  if (sop_id && validationResults.length === 0 && !loading) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <p className="text-muted-foreground">No P&IDs linked to this SOP yet.</p>
          <p className="text-sm text-muted-foreground">Run validation from the Dashboard to find matching P&IDs.</p>
          <button type="button" onClick={() => navigate('/')} className="text-sm text-primary hover:underline">Go to Dashboard</button>
        </div>
      </AppLayout>
    );
  }

  if (loading) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <Loader2 className="h-10 w-10 text-primary animate-spin" />
          <p className="text-sm text-muted-foreground">Loading validation…</p>
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
      {/* Floating header */}
      <div className="relative z-20 flex justify-center px-6 pt-3">
        <div className="glass-strong rounded-full px-3 py-1.5 flex items-center gap-2 shadow-lg shadow-black/20">
          <span className="text-[13px] font-semibold text-foreground px-2">Validation</span>
          <span className="text-[10px] text-muted-foreground font-mono bg-white/[0.06] px-2 py-0.5 rounded-full">{sop_id ? `SOP: ${sopFileName ?? '…'}` : displayPidId}</span>
          <div className="h-4 w-px bg-white/[0.08] mx-1" />
          <span className="flex items-center gap-1.5 text-[11px]">
            <span className="h-2 w-2 rounded-full bg-destructive" />
            <span className="text-destructive font-semibold">{validation.issues.filter(i => (i.severity||'error')==='error').length}</span>
          </span>
          <span className="flex items-center gap-1.5 text-[11px]">
            <span className="h-2 w-2 rounded-full bg-warning" />
            <span className="text-warning font-semibold">{validation.issues.filter(i => i.severity==='warning').length}</span>
          </span>
          <span className="text-[11px] text-muted-foreground font-medium">{validation.issues.length} total</span>
        </div>
      </div>

      <div className="flex flex-1 min-h-0 px-4 pb-10 pt-3 gap-3">
        {/* Issues sidebar */}
        <div className="w-[280px] glass rounded-2xl flex flex-col shrink-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">Issues</span>
          </div>
          <div className="flex-1 overflow-y-auto p-1.5">
            {validation.issues.map((issue, i) => {
              const severity = issue.severity || 'error';
              const isSelected = selectedIssueIndex === i;
              return (
                <button
                  key={i}
                  onClick={() => handleIssueClick(issue, i)}
                  className={`w-full text-left px-3 py-3 rounded-xl mb-0.5 transition-all ${
                    isSelected ? 'bg-white/[0.06]' : 'hover:bg-white/[0.03]'
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    <div className={`h-2 w-2 rounded-full mt-1.5 shrink-0 ${severityDot[severity]}`} />
                    <div className="min-w-0">
                      <p className="text-[12px] font-semibold text-foreground truncate">
                        {issue.component || issue.type.replace(/_/g, ' ')}
                      </p>
                      <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2 leading-relaxed">{issue.description}</p>
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Graph */}
        <div className="flex-1 relative glass rounded-2xl overflow-hidden">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.25 }}
            minZoom={0.3}
            maxZoom={2}
            defaultEdgeOptions={{ type: 'smoothstep' }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={28} size={1} color="hsla(228, 12%, 16%, 0.5)" />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        {/* Detail panel */}
        <div className="w-[280px] glass rounded-2xl flex flex-col shrink-0 overflow-hidden">
          <div className="px-4 py-3 border-b border-white/[0.06]">
            <span className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">Details</span>
          </div>
          {selectedIssue ? (
            <div className="p-4 space-y-4">
              <div className="rounded-xl p-4 bg-white/[0.03]">
                <div className="flex items-center gap-2 mb-2">
                  <div className={`h-2 w-2 rounded-full ${severityDot[selectedIssue.severity || 'error']}`} />
                  <span className="text-[10px] font-semibold text-muted-foreground capitalize tracking-wider">{selectedIssue.type.replace(/_/g, ' ')}</span>
                </div>
                {selectedIssue.component && (
                  <p className="text-[14px] font-semibold text-foreground mb-1.5">{selectedIssue.component}</p>
                )}
                <p className="text-[12px] text-muted-foreground leading-relaxed">{selectedIssue.description}</p>
              </div>

              {selectedIssue.relatedNodes && selectedIssue.relatedNodes.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-2">Affected</p>
                  <div className="space-y-1">
                    {selectedIssue.relatedNodes.map(id => {
                      const node = graph.nodes.find(n => n.id === id);
                      return node ? (
                        <div key={id} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.03]">
                          <div className="h-2 w-2 rounded-full" style={{ backgroundColor: NODE_COLORS[node.type] }} />
                          <span className="text-[11px] text-foreground font-medium">{node.label}</span>
                          <span className="text-[10px] text-muted-foreground capitalize ml-auto">{node.type}</span>
                        </div>
                      ) : null;
                    })}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center p-6">
              <p className="text-[12px] text-muted-foreground text-center">Select an issue to inspect</p>
            </div>
          )}
        </div>
      </div>
      {validationResults.length > 1 && (
        <div className="px-4 pb-4">
          <div className="flex justify-center">
            <div className="glass-strong rounded-full px-2 py-1.5">
              <DiagramSwitcher results={validationResults} currentPidId={displayPidId ?? ''} basePath="/validation" />
            </div>
          </div>
        </div>
      )}
    </AppLayout>
  );
}
