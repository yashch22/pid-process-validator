import { useMemo, useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import AppLayout from '@/components/layout/AppLayout';
import DiagramSwitcher from '@/components/diagram/DiagramSwitcher';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip } from 'recharts';
import { getGraph, getValidation } from '@/lib/api';
import { usePidStore } from '@/store/usePidStore';
import { NODE_COLORS } from '@/lib/graph-utils';
import { Download, Boxes, GitBranch, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import type { ComponentType, Graph, ValidationResult } from '@/types/graph';

const severityDot: Record<string, string> = { error: 'bg-destructive', warning: 'bg-warning', info: 'bg-info' };

const emptyGraph: Graph = { nodes: [], edges: [] };
const emptyValidation: ValidationResult = { status: 'pending', issues: [] };

export default function ReportPage() {
  const { pid_id } = useParams<{ pid_id: string }>();
  const navigate = useNavigate();
  const { currentPidId, graph: storeGraph, validation: storeValidation, validationResults, setPidId, setGraph, setValidation } = usePidStore();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const graph = storeGraph || emptyGraph;
  const validation = storeValidation || emptyValidation;

  useEffect(() => {
    if (!pid_id) {
      setLoading(false);
      return;
    }
    if (storeGraph && storeValidation && currentPidId === pid_id) {
      setLoading(false);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([getGraph(pid_id), getValidation(pid_id)])
      .then(([graphData, validationData]) => {
        if (!cancelled) {
          setPidId(pid_id);
          setGraph(graphData);
          setValidation(validationData);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load report');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [pid_id, currentPidId, storeGraph, storeValidation, setPidId, setGraph, setValidation]);

  const componentBreakdown = useMemo(() => {
    const counts: Record<string, number> = {};
    graph.nodes.forEach(n => { counts[n.type] = (counts[n.type] || 0) + 1; });
    return Object.entries(counts).map(([type, count]) => ({
      name: type.charAt(0).toUpperCase() + type.slice(1),
      value: count,
      color: NODE_COLORS[type as ComponentType] || '#888',
    }));
  }, [graph]);

  const handleExport = () => {
    const data = { graph, validation, generatedAt: new Date().toISOString() };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `report-${pid_id}.json`; a.click();
    URL.revokeObjectURL(url);
  };

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
          <p className="text-sm text-muted-foreground">Loading report…</p>
        </div>
      </AppLayout>
    );
  }

  if (error) {
    return (
      <AppLayout>
        <div className="flex-1 flex flex-col items-center justify-center gap-4">
          <AlertTriangle className="h-10 w-10 text-destructive" />
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
          <span className="text-[13px] font-semibold text-foreground px-2">Report</span>
          <span className="text-[10px] text-muted-foreground font-mono bg-white/[0.06] px-2 py-0.5 rounded-full">{pid_id}</span>
          <div className="h-4 w-px bg-white/[0.08] mx-1" />
          <button
            onClick={handleExport}
            className="flex items-center gap-1.5 text-[12px] text-muted-foreground hover:text-foreground px-3 py-1 rounded-full hover:bg-white/[0.06] transition-all font-medium"
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[900px] mx-auto px-6 py-8">
          {/* Stats */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className="grid grid-cols-4 gap-3 mb-8"
          >
            {[
              { label: 'Components', value: graph.nodes.length, icon: Boxes },
              { label: 'Connections', value: graph.edges.length, icon: GitBranch },
              { label: 'Issues', value: validation.issues.length, icon: AlertTriangle },
              { label: 'Status', value: 'Done', icon: CheckCircle2 },
            ].map((stat, i) => (
              <div key={i} className="glass rounded-2xl px-5 py-4">
                <div className="flex items-center gap-2 mb-2">
                  <stat.icon className="h-4 w-4 text-muted-foreground" />
                  <span className="text-[11px] text-muted-foreground font-medium">{stat.label}</span>
                </div>
                <p className="text-[24px] font-bold text-foreground tracking-[-0.04em]">{stat.value}</p>
              </div>
            ))}
          </motion.div>

          <div className="grid grid-cols-2 gap-3 mb-8">
            {/* Chart */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.5 }}
              className="glass rounded-2xl p-5"
            >
              <p className="text-[14px] font-semibold text-foreground mb-4">Component Breakdown</p>
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={componentBreakdown} dataKey="value" nameKey="name" cx="50%" cy="50%" outerRadius={65} innerRadius={40} strokeWidth={0}>
                    {componentBreakdown.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      background: 'hsla(228,14%,8%,0.95)',
                      border: '1px solid hsla(228,12%,18%,0.5)',
                      borderRadius: '12px',
                      color: 'hsl(0,0%,95%)',
                      fontSize: '12px',
                      backdropFilter: 'blur(16px)',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 mt-3">
                {componentBreakdown.map((e, i) => (
                  <div key={i} className="flex items-center gap-1.5">
                    <div className="h-2 w-2 rounded-full" style={{ backgroundColor: e.color }} />
                    <span className="text-[11px] text-muted-foreground">{e.name} ({e.value})</span>
                  </div>
                ))}
              </div>
            </motion.div>

            {/* Metrics */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15, duration: 0.5 }}
              className="glass rounded-2xl p-5"
            >
              <p className="text-[14px] font-semibold text-foreground mb-4">Graph Metrics</p>
              <div className="space-y-0.5">
                {[
                  { k: 'Nodes', v: graph.nodes.length },
                  { k: 'Edges', v: graph.edges.length },
                  { k: 'Density', v: graph.nodes.length < 2 ? '0' : (2 * graph.edges.length / (graph.nodes.length * (graph.nodes.length - 1))).toFixed(3) },
                  { k: 'Avg Degree', v: graph.nodes.length === 0 ? '0' : (2 * graph.edges.length / graph.nodes.length).toFixed(1) },
                  { k: 'Types', v: new Set(graph.nodes.map(n => n.type)).size },
                ].map((m, i) => (
                  <div key={i} className="flex justify-between py-2.5 px-3 rounded-xl hover:bg-white/[0.03] transition-colors">
                    <span className="text-[12px] text-muted-foreground">{m.k}</span>
                    <span className="text-[12px] font-semibold text-foreground font-mono">{m.v}</span>
                  </div>
                ))}
              </div>
            </motion.div>
          </div>

          {/* Issues Table */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.5 }}
            className="glass rounded-2xl overflow-hidden"
          >
            <div className="px-5 py-4 border-b border-white/[0.06]">
              <p className="text-[14px] font-semibold text-foreground">Validation Results</p>
            </div>
            <Table>
              <TableHeader>
                <TableRow className="border-white/[0.04] hover:bg-transparent">
                  <TableHead className="text-[10px] font-semibold text-muted-foreground h-9 uppercase tracking-widest">Type</TableHead>
                  <TableHead className="text-[10px] font-semibold text-muted-foreground h-9 uppercase tracking-widest">Component</TableHead>
                  <TableHead className="text-[10px] font-semibold text-muted-foreground h-9 uppercase tracking-widest">Description</TableHead>
                  <TableHead className="text-[10px] font-semibold text-muted-foreground h-9 uppercase tracking-widest w-24">Severity</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {validation.issues.map((issue, i) => (
                  <TableRow key={i} className="border-white/[0.04] hover:bg-white/[0.02]">
                    <TableCell className="text-[12px] capitalize py-3">{issue.type.replace(/_/g, ' ')}</TableCell>
                    <TableCell className="text-[12px] font-semibold py-3">{issue.component || '—'}</TableCell>
                    <TableCell className="text-[12px] text-muted-foreground py-3 max-w-[300px]">{issue.description}</TableCell>
                    <TableCell className="py-3">
                      <div className="flex items-center gap-1.5">
                        <div className={`h-2 w-2 rounded-full ${severityDot[issue.severity || 'error']}`} />
                        <span className="text-[11px] capitalize text-muted-foreground">{issue.severity || 'error'}</span>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </motion.div>
        </div>
        {validationResults.length > 1 && (
          <div className="px-6 pb-6">
            <div className="flex justify-center">
              <div className="glass-strong rounded-full px-2 py-1.5">
                <DiagramSwitcher results={validationResults} currentPidId={pid_id} basePath="/report" />
              </div>
            </div>
          </div>
        )}
      </div>
    </AppLayout>
  );
}
