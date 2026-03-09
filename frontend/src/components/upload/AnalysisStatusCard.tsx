import { motion } from 'framer-motion';
import { Activity, CheckCircle2, AlertTriangle, Clock, ArrowRight } from 'lucide-react';

interface StatusProps {
  pidUploaded: boolean;
  sopUploaded: boolean;
  validated: boolean;
  issueCount: number;
}

export default function AnalysisStatusCard({ pidUploaded, sopUploaded, validated, issueCount }: StatusProps) {
  const steps = [
    { label: 'P&ID Uploaded', sublabel: 'Graph extraction', done: pidUploaded, icon: CheckCircle2 },
    { label: 'SOP Uploaded', sublabel: 'Document parsed', done: sopUploaded, icon: CheckCircle2 },
    { label: 'Validation Complete', sublabel: `${issueCount} issues found`, done: validated, icon: validated ? (issueCount > 0 ? AlertTriangle : CheckCircle2) : Clock },
  ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
      className="glass rounded-2xl gradient-border overflow-hidden"
    >
      <div className="p-5">
        <div className="flex items-center gap-2.5 mb-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/10">
            <Activity className="h-4 w-4 text-primary" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-foreground">Pipeline Status</h3>
            <p className="text-[10px] text-muted-foreground">Analysis workflow</p>
          </div>
        </div>
        <div className="space-y-1">
          {steps.map((step, i) => (
            <div key={i} className="relative">
              <div className={`flex items-center gap-3 rounded-xl px-3 py-2.5 transition-colors ${
                step.done ? 'bg-white/[0.03]' : ''
              }`}>
                <div className={`flex h-7 w-7 items-center justify-center rounded-lg shrink-0 ${
                  step.done
                    ? step.label.includes('Validation') && issueCount > 0
                      ? 'bg-warning/10'
                      : 'bg-success/10'
                    : 'bg-white/[0.04]'
                }`}>
                  <step.icon className={`h-3.5 w-3.5 ${
                    step.done
                      ? step.label.includes('Validation') && issueCount > 0
                        ? 'text-warning'
                        : 'text-success'
                      : 'text-muted-foreground/50'
                  }`} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-xs font-medium ${step.done ? 'text-foreground' : 'text-muted-foreground'}`}>{step.label}</p>
                  <p className="text-[10px] text-muted-foreground/60">{step.sublabel}</p>
                </div>
                {step.done && <ArrowRight className="h-3 w-3 text-muted-foreground/30" />}
              </div>
              {i < steps.length - 1 && (
                <div className={`absolute left-[1.6rem] top-[2.5rem] w-px h-1.5 ${step.done ? 'bg-success/20' : 'bg-white/[0.04]'}`} />
              )}
            </div>
          ))}
        </div>
      </div>
    </motion.div>
  );
}
