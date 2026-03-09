import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { Badge } from '@/components/ui/badge';
import { usePidStore } from '@/store/usePidStore';
import { format } from 'date-fns';
import { Clock, ArrowUpRight, FileText } from 'lucide-react';

const statusStyles: Record<string, { bg: string; text: string }> = {
  uploaded: { bg: 'bg-muted/50', text: 'text-muted-foreground' },
  graph_ready: { bg: 'bg-primary/10', text: 'text-primary' },
  sop_uploaded: { bg: 'bg-warning/10', text: 'text-warning' },
  validated: { bg: 'bg-success/10', text: 'text-success' },
};

export default function RecentRunsTable() {
  const runs = usePidStore((s) => s.runs);
  const navigate = useNavigate();

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="glass rounded-2xl gradient-border overflow-hidden"
    >
      <div className="p-5 pb-3">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-white/[0.04]">
            <Clock className="h-4 w-4 text-muted-foreground" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">Recent Analyses</h3>
            <p className="text-[10px] text-muted-foreground">{runs.length} runs</p>
          </div>
        </div>
      </div>
      <div className="px-3 pb-3 space-y-1">
        {runs.map((run, i) => {
          const style = statusStyles[run.status] || statusStyles.uploaded;
          return (
            <motion.button
              key={run.pid_id}
              initial={{ opacity: 0, x: -8 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: 0.25 + i * 0.05 }}
              onClick={() => navigate(`/graph/${run.pid_id}`)}
              className="w-full flex items-center gap-3 rounded-xl px-3 py-3 text-left hover:bg-white/[0.03] transition-all duration-200 group"
            >
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-white/[0.04] shrink-0 group-hover:bg-primary/10 transition-colors">
                <FileText className="h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="text-xs font-semibold text-foreground truncate">{run.filename}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  <Badge variant="secondary" className={`text-[9px] font-semibold px-1.5 py-0 h-4 border-0 ${style.bg} ${style.text}`}>
                    {run.status.replace('_', ' ')}
                  </Badge>
                  {run.issueCount !== undefined && run.issueCount > 0 && (
                    <span className="text-[10px] text-warning font-medium">{run.issueCount} issues</span>
                  )}
                </div>
              </div>
              <div className="flex flex-col items-end gap-1 shrink-0">
                <span className="text-[10px] text-muted-foreground">{format(new Date(run.timestamp), 'MMM d')}</span>
                <ArrowUpRight className="h-3 w-3 text-muted-foreground/30 group-hover:text-primary transition-colors" />
              </div>
            </motion.button>
          );
        })}
      </div>
    </motion.div>
  );
}
