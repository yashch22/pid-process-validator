import { X } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import type { GraphNode } from '@/types/graph';
import { NODE_COLORS, NODE_ICONS } from '@/lib/graph-utils';

interface Props {
  node: GraphNode | null;
  connectedNodes: GraphNode[];
  onClose: () => void;
}

export default function NodeDetailPanel({ node, connectedNodes, onClose }: Props) {
  return (
    <AnimatePresence>
      {node && (
        <motion.div
          initial={{ x: 320, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 320, opacity: 0 }}
          transition={{ type: 'spring', bounce: 0.08, duration: 0.5 }}
          className="absolute right-4 top-4 bottom-4 w-[300px] glass-strong rounded-2xl z-10 overflow-y-auto shadow-2xl shadow-black/30"
        >
          <div className="flex items-center justify-between px-5 py-4 border-b border-border/50">
            <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-widest">Details</span>
            <button onClick={onClose} className="rounded-xl p-2 hover:bg-white/[0.06] text-muted-foreground transition-colors">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="p-5 space-y-5">
            <div className="flex items-center gap-3.5">
              <div
                className="flex h-11 w-11 items-center justify-center text-base font-bold"
                style={{
                  backgroundColor: NODE_COLORS[node.type] + '12',
                  color: NODE_COLORS[node.type],
                  borderRadius: 14,
                  boxShadow: `0 0 20px ${NODE_COLORS[node.type]}15`,
                }}
              >
                {NODE_ICONS[node.type]}
              </div>
              <div>
                <p className="text-[15px] font-semibold text-foreground tracking-[-0.01em]">{node.label}</p>
                <p className="text-[11px] text-muted-foreground capitalize mt-0.5">{node.type}</p>
              </div>
            </div>

            <div>
              <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-3">Attributes</p>
              <div className="rounded-xl overflow-hidden border border-border/40">
                {Object.entries(node.attributes).map(([key, value], i) => (
                  <div key={key} className={`flex justify-between px-4 py-2.5 ${i > 0 ? 'border-t border-border/30' : ''}`}
                    style={{ background: i % 2 === 0 ? 'hsla(228,14%,10%,0.4)' : 'transparent' }}>
                    <span className="text-[11px] text-muted-foreground capitalize">{key.replace('_', ' ')}</span>
                    <span className="text-[11px] font-medium text-foreground font-mono">{value}</span>
                  </div>
                ))}
              </div>
            </div>

            {connectedNodes.length > 0 && (
              <div>
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-widest mb-3">
                  Connected ({connectedNodes.length})
                </p>
                <div className="space-y-1.5">
                  {connectedNodes.map((cn) => (
                    <div key={cn.id} className="flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl hover:bg-white/[0.04] transition-colors">
                      <div
                        className="h-2.5 w-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: NODE_COLORS[cn.type], boxShadow: `0 0 6px ${NODE_COLORS[cn.type]}40` }}
                      />
                      <span className="text-[12px] text-foreground font-medium">{cn.label}</span>
                      <span className="text-[10px] text-muted-foreground capitalize ml-auto">{cn.type}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
