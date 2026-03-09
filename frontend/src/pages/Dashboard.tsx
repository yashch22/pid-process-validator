import { useState, useCallback, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import AppLayout from '@/components/layout/AppLayout';
import { usePidStore } from '@/store/usePidStore';
import { toast } from 'sonner';
import { motion } from 'framer-motion';
import {
  Play, ArrowRight, ArrowUpRight, GitBranch, Upload, FileText,
  CheckCircle2, AlertTriangle, BarChart3, Boxes, Clock, Loader2, Sparkles, ClipboardList
} from 'lucide-react';
import { format } from 'date-fns';
import { uploadPid, getGraph, getValidation, uploadSop, validateSopById, listPids, listSops } from '@/lib/api';
import type { AnalysisRun, RecentItem } from '@/types/graph';

export default function Dashboard() {
  const navigate = useNavigate();
  const { currentPidId, setPidId, setGraph, setValidation, setValidationResults, addRun, setRuns, runs, graph: storeGraph, validation: storeValidation, validationResults } = usePidStore();
  const [pidUploaded, setPidUploaded] = useState(false);
  const [sopUploaded, setSopUploaded] = useState(false);
  const [validated, setValidated] = useState(false);
  const [running, setRunning] = useState(false);
  const [pidFile, setPidFile] = useState<File | null>(null);
  const [sopFile, setSopFile] = useState<File | null>(null);
  const [sopId, setSopId] = useState<string | null>(null);
  const [uploadingPid, setUploadingPid] = useState(false);
  const [uploadingSop, setUploadingSop] = useState(false);
  const [loadingRuns, setLoadingRuns] = useState(true);
  const [sops, setSops] = useState<Array<{ sop_id: string; file_name?: string; created_at: string }>>([]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([listPids(), listSops()])
      .then(([{ pids }, { sops: sopsList }]) => {
        if (!cancelled) {
          const runsData: AnalysisRun[] = pids.map((p) => ({
            pid_id: p.pid_id,
            filename: p.filename,
            sopFilename: p.sopFilename,
            timestamp: p.timestamp,
            status: p.status,
            issueCount: p.issueCount,
          }));
          setRuns(runsData);
          setSops(sopsList);
          if (pids.length > 0) {
            const first = pids[0];
            setPidId(first.pid_id);
            getGraph(first.pid_id)
              .then((g) => { if (!cancelled) setGraph(g); })
              .catch(() => {});
            getValidation(first.pid_id)
              .then((v) => { if (!cancelled) setValidation(v); })
              .catch(() => {});
          }
        }
      })
      .catch(() => {})
      .finally(() => { if (!cancelled) setLoadingRuns(false); });
    return () => { cancelled = true; };
  }, [setRuns, setPidId, setGraph, setValidation]);

  const recentItems: RecentItem[] = useMemo(() => {
    const pidItems: RecentItem[] = runs.map((r) => ({
      type: 'pid',
      id: r.pid_id,
      pid_id: r.pid_id,
      filename: r.filename,
      sopFilename: r.sopFilename,
      timestamp: r.timestamp,
      status: r.status,
      issueCount: r.issueCount,
    }));
    const sopItems: RecentItem[] = sops.map((s) => ({
      type: 'sop',
      id: s.sop_id,
      sop_id: s.sop_id,
      filename: s.file_name || 'SOP',
      timestamp: s.created_at,
    }));
    return [...pidItems, ...sopItems].sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );
  }, [runs, sops]);

  const handlePidUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPidFile(file);
    setUploadingPid(true);
    try {
      const { pid_id } = await uploadPid(file);
      setPidId(pid_id);
      const graph = await getGraph(pid_id);
      setGraph(graph);
      setPidUploaded(true);
      addRun({
        pid_id,
        filename: file.name,
        timestamp: new Date().toISOString(),
        status: 'graph_ready',
      });
      toast.success('P&ID processed — graph extracted');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Upload failed';
      toast.error(msg);
    } finally {
      setUploadingPid(false);
    }
  }, [setPidId, setGraph, addRun]);

  const handleSopUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setSopFile(file);
    setUploadingSop(true);
    try {
      const { sop_id } = await uploadSop(file);
      setSopId(sop_id);
      setSopUploaded(true);
      setSops((prev) => [{ sop_id, file_name: file.name, created_at: new Date().toISOString() }, ...prev]);
      toast.success('SOP uploaded — matching P&IDs will be found when validating');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'SOP upload failed';
      toast.error(msg);
    } finally {
      setUploadingSop(false);
    }
  }, []);

  const handleValidate = useCallback(async () => {
    if (!sopId || !sopUploaded) return;
    setRunning(true);
    try {
      const { results } = await validateSopById(sopId);
      setValidationResults(results);
      setValidated(true);
      const totalIssues = results.reduce((n, r) => n + (r.issues?.length ?? 0), 0);
      if (results.length > 0) {
        setPidId(results[0].pid_id);
        setValidation({ status: results[0].status, issues: results[0].issues ?? [] });
        const graph = await getGraph(results[0].pid_id);
        setGraph(graph);
        results.forEach((r) => addRun({ pid_id: r.pid_id, filename: r.file_name ?? 'P&ID', sopFilename: sopFile?.name, timestamp: new Date().toISOString(), status: 'validated', issueCount: r.issues?.length ?? 0 }));
      }
      toast.success(`Validation complete — ${results.length} P&ID(s) matched, ${totalIssues} issue(s) found`);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Validation failed';
      toast.error(msg);
    } finally {
      setRunning(false);
    }
  }, [sopId, sopUploaded, setValidation, setPidId, setGraph, addRun, sopFile?.name]);

  const handleRecentItemClick = useCallback(
    async (item: RecentItem) => {
      if (item.type === 'pid') {
        navigate(`/graph/${item.pid_id}`);
      } else {
        setRunning(true);
        const loadingId = toast.loading('Validating SOP against P&IDs…');
        try {
          const { results } = await validateSopById(item.sop_id);
          toast.dismiss(loadingId);
          setValidationResults(results);
          setValidated(true);
          if (results.length > 0) {
            setPidId(results[0].pid_id);
            setValidation({ status: results[0].status, issues: results[0].issues ?? [] });
            const graph = await getGraph(results[0].pid_id);
            setGraph(graph);
            results.forEach((r) => addRun({ pid_id: r.pid_id, filename: r.file_name ?? 'P&ID', sopFilename: item.filename, timestamp: new Date().toISOString(), status: 'validated', issueCount: r.issues?.length ?? 0 }));
            navigate(`/validation/sop/${item.sop_id}`);
          } else {
            toast.warning('No matching P&IDs found. Upload P&ID documents first, then run validation from the workflow above.', { duration: 6000 });
          }
        } catch (err: unknown) {
          toast.dismiss(loadingId);
          toast.error(err instanceof Error ? err.message : 'Validation failed');
        } finally {
          setRunning(false);
        }
      }
    },
    [navigate, setValidationResults, setPidId, setValidation, setGraph, addRun]
  );

  const statusColor: Record<string, string> = {
    uploaded: 'text-muted-foreground',
    graph_ready: 'text-primary',
    sop_uploaded: 'text-warning',
    validated: 'text-success',
  };

  return (
    <AppLayout>
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-[960px] mx-auto px-6 py-10">

          {/* ── Hero ── */}
          <motion.section
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
            className="text-center mb-12"
          >
            <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-primary/8 border border-primary/15 mb-5">
              <Sparkles className="h-3 w-3 text-primary" />
              <span className="text-[11px] font-semibold text-primary tracking-wide">AI-Powered Analysis</span>
            </div>
            <h1 className="text-[32px] font-bold text-foreground tracking-[-0.04em] leading-[1.15]">
              P&ID Graph Intelligence
            </h1>
            <p className="text-[15px] text-muted-foreground mt-3 max-w-md mx-auto leading-relaxed">
              Extract, visualize, and validate piping & instrumentation diagrams with intelligent graph analysis.
            </p>
          </motion.section>

          {/* ── Upload Workflow ── */}
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1, duration: 0.5 }}
            className="glass rounded-2xl p-6 mb-8"
          >
            <div className="flex items-center gap-2 mb-5">
              <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest">New Analysis</span>
              <div className="flex-1 h-px bg-border/40" />
            </div>

            <div className="grid grid-cols-3 gap-4">
              {/* Step 1 — P&ID */}
              <div className="relative">
                <div className="flex items-center gap-2 mb-3">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">1</div>
                  <span className="text-[12px] font-semibold text-foreground">P&ID Document</span>
                  {pidUploaded && <CheckCircle2 className="h-3.5 w-3.5 text-success ml-auto" />}
                </div>
                {pidUploaded ? (
                  <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-success/[0.06] border border-success/15">
                    <FileText className="h-3.5 w-3.5 text-success" />
                    <span className="text-[11px] text-success font-semibold">Processed</span>
                    <span className="text-[10px] text-muted-foreground ml-auto font-mono truncate max-w-[80px]">{pidFile?.name}</span>
                  </div>
                ) : (
                  <label className={`flex flex-col items-center gap-2 px-4 py-5 rounded-xl border border-dashed border-border/60 transition-all duration-300 group ${uploadingPid ? 'opacity-60 cursor-wait' : 'cursor-pointer hover:border-primary/30 hover:bg-primary/[0.02]'}`}>
                    <div className="h-9 w-9 rounded-full bg-white/[0.04] flex items-center justify-center group-hover:bg-primary/10 transition-colors">
                      {uploadingPid ? <Loader2 className="h-4 w-4 text-primary animate-spin" /> : <Upload className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />}
                    </div>
                    <span className="text-[11px] text-muted-foreground font-medium">{uploadingPid ? 'Processing…' : 'Upload PDF or image'}</span>
                    <input type="file" accept=".pdf,.png,.jpg,.jpeg,.tiff" className="hidden" onChange={handlePidUpload} disabled={uploadingPid} />
                  </label>
                )}
              </div>

              {/* Step 2 — SOP */}
              <div className="relative">
                <div className="flex items-center gap-2 mb-3">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-warning/10 text-[10px] font-bold text-warning">2</div>
                  <span className="text-[12px] font-semibold text-foreground">SOP Document</span>
                  {sopUploaded && <CheckCircle2 className="h-3.5 w-3.5 text-success ml-auto" />}
                </div>
                {sopUploaded ? (
                  <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-success/[0.06] border border-success/15">
                    <FileText className="h-3.5 w-3.5 text-success" />
                    <span className="text-[11px] text-success font-semibold">Ready</span>
                    <span className="text-[10px] text-muted-foreground ml-auto font-mono truncate max-w-[80px]">{sopFile?.name}</span>
                  </div>
                ) : (
                  <label className={`flex flex-col items-center gap-2 px-4 py-5 rounded-xl border border-dashed border-border/60 transition-all duration-300 group ${uploadingSop ? 'opacity-60 cursor-wait' : 'cursor-pointer hover:border-warning/30 hover:bg-warning/[0.02]'}`}>
                    <div className="h-9 w-9 rounded-full bg-white/[0.04] flex items-center justify-center group-hover:bg-warning/10 transition-colors">
                      {uploadingSop ? <Loader2 className="h-4 w-4 text-warning animate-spin" /> : <Upload className="h-4 w-4 text-muted-foreground group-hover:text-warning transition-colors" />}
                    </div>
                    <span className="text-[11px] text-muted-foreground font-medium">{uploadingSop ? 'Uploading…' : 'Upload DOCX or TXT'}</span>
                    <input type="file" accept=".docx,.doc,.txt" className="hidden" onChange={handleSopUpload} disabled={uploadingSop} />
                  </label>
                )}
              </div>

              {/* Step 3 — Validate */}
              <div>
                <div className="flex items-center gap-2 mb-3">
                  <div className="flex h-6 w-6 items-center justify-center rounded-full bg-success/10 text-[10px] font-bold text-success">3</div>
                  <span className="text-[12px] font-semibold text-foreground">Validate</span>
                  {validated && <CheckCircle2 className="h-3.5 w-3.5 text-success ml-auto" />}
                </div>
                {validated ? (
                  <button
                    onClick={() => sopId && validationResults.length > 0 && navigate(`/validation/sop/${sopId}`)}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-primary/10 text-primary text-[12px] font-semibold hover:bg-primary/15 border border-primary/20 transition-all"
                  >
                    View Results <ArrowRight className="h-3.5 w-3.5" />
                  </button>
                ) : (
                  <button
                    onClick={handleValidate}
                    disabled={!sopUploaded || running}
                    className="w-full flex items-center justify-center gap-2 px-4 py-3.5 rounded-xl bg-primary text-primary-foreground text-[12px] font-semibold hover:bg-primary/90 disabled:opacity-25 disabled:cursor-not-allowed transition-all"
                  >
                    {running ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                    {running ? 'Analyzing...' : 'Run Validation'}
                  </button>
                )}
              </div>
            </div>
          </motion.section>

          {/* ── Stats ── */}
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.2, duration: 0.5 }}
            className="grid grid-cols-4 gap-3 mb-8"
          >
            {[
              { label: 'Components', value: storeGraph ? String(storeGraph.nodes.length) : '—', icon: Boxes },
              { label: 'Connections', value: storeGraph ? String(storeGraph.edges.length) : '—', icon: GitBranch },
              { label: 'Issues', value: storeValidation ? String(storeValidation.issues.length) : '—', icon: AlertTriangle },
              { label: 'Types', value: storeGraph ? String(new Set(storeGraph.nodes.map((n) => n.type)).size) : '—', icon: BarChart3 },
            ].map((stat, i) => (
              <div
                key={i}
                className="glass rounded-2xl px-5 py-4 group hover:bg-white/[0.04] transition-all duration-300"
              >
                <div className="flex items-center gap-2 mb-3">
                  <stat.icon className="h-4 w-4 text-muted-foreground" />
                  <span className="text-[11px] text-muted-foreground font-medium">{stat.label}</span>
                </div>
                <p className="text-[26px] font-bold text-foreground tracking-[-0.04em]">{stat.value}</p>
              </div>
            ))}
          </motion.section>

          {/* ── Recent Analyses ── */}
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.3, duration: 0.5 }}
          >
            <div className="flex items-center gap-2 mb-4">
              <Clock className="h-4 w-4 text-muted-foreground" />
              <h2 className="text-[14px] font-semibold text-foreground">Recent Analyses</h2>
              <div className="flex-1 h-px bg-border/30" />
              <span className="text-[11px] text-muted-foreground">{recentItems.length} items</span>
            </div>
            <div className="glass rounded-2xl overflow-hidden divide-y divide-border/20">
              {recentItems.map((item) => (
                <button
                  key={item.id}
                  onClick={() => handleRecentItemClick(item)}
                  disabled={item.type === 'sop' && running}
                  className="w-full flex items-center gap-4 px-5 py-4 hover:bg-white/[0.03] transition-all text-left group disabled:opacity-50"
                >
                  <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.04] shrink-0 group-hover:bg-primary/10 transition-colors">
                    {item.type === 'pid' ? (
                      <FileText className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
                    ) : (
                      <ClipboardList className="h-4 w-4 text-muted-foreground group-hover:text-warning transition-colors" />
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-[13px] font-semibold text-foreground truncate">{item.filename}</p>
                    <p className="text-[11px] text-muted-foreground mt-0.5">
                      {item.type === 'pid'
                        ? `${item.sopFilename || 'No SOP'} · ${format(new Date(item.timestamp), 'MMM d, HH:mm')}`
                        : `SOP · ${format(new Date(item.timestamp), 'MMM d, HH:mm')}`}
                    </p>
                  </div>
                  <span className={`text-[10px] font-semibold uppercase px-2 py-0.5 rounded-full ${item.type === 'pid' ? 'bg-primary/10 text-primary' : 'bg-warning/10 text-warning'}`}>
                    {item.type === 'pid' ? 'P&ID' : 'SOP'}
                  </span>
                  {item.type === 'pid' && (
                    <span className={`text-[11px] font-semibold capitalize px-2.5 py-1 rounded-full bg-white/[0.04] ${statusColor[item.status]}`}>
                      {item.status.replace('_', ' ')}
                    </span>
                  )}
                  {item.type === 'pid' && item.issueCount !== undefined && item.issueCount > 0 && (
                    <span className="text-[11px] text-warning font-semibold bg-warning/10 px-2.5 py-1 rounded-full">{item.issueCount} issues</span>
                  )}
                  <ArrowUpRight className="h-4 w-4 text-muted-foreground/20 group-hover:text-primary transition-colors" />
                </button>
              ))}
            </div>
          </motion.section>

        </div>
      </div>
    </AppLayout>
  );
}
