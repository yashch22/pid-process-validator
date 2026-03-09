import { useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import type { ValidationResultItem } from '@/store/usePidStore';

interface DiagramSwitcherProps {
  results: ValidationResultItem[];
  currentPidId: string;
  basePath: '/graph' | '/validation' | '/report';
}

function getDiagramLabel(r: ValidationResultItem, index: number, results: ValidationResultItem[]): string {
  const base = r.file_name || 'P&ID';
  if (r.page_num != null) return `${base} · Page ${r.page_num}`;
  const sameNameCount = results.filter((x) => (x.file_name || 'P&ID') === base).length;
  if (sameNameCount > 1) return `${base} · ${index + 1}`;
  return base;
}

export default function DiagramSwitcher({ results, currentPidId, basePath }: DiagramSwitcherProps) {
  const navigate = useNavigate();
  const scrollRef = useRef<HTMLDivElement>(null);
  const currentIndex = results.findIndex((r) => r.pid_id === currentPidId);
  const showSwitcher = results.length > 1 && currentIndex >= 0;

  useEffect(() => {
    const el = scrollRef.current;
    const active = el?.querySelector('[data-active="true"]');
    if (el && active) active.scrollIntoView({ block: 'nearest', inline: 'center', behavior: 'smooth' });
  }, [currentPidId, currentIndex]);

  const goTo = (index: number) => {
    const r = results[index];
    if (r) navigate(`${basePath}/${r.pid_id}`);
  };

  if (!showSwitcher) return null;

  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={() => goTo(Math.max(0, currentIndex - 1))}
        disabled={currentIndex <= 0}
        className="p-1 rounded-full text-muted-foreground hover:text-foreground hover:bg-white/[0.06] disabled:opacity-30 disabled:cursor-not-allowed transition-all"
        aria-label="Previous diagram"
      >
        <ChevronLeft className="h-4 w-4" />
      </button>

      <div
        ref={scrollRef}
        className="flex gap-1 overflow-x-auto scroll-smooth scrollbar-none max-w-[180px] sm:max-w-[220px] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
      >
        {results.map((r, i) => {
          const isActive = r.pid_id === currentPidId;
          const label = getDiagramLabel(r, i, results);
          const issueCount = r.issues?.length ?? 0;
          return (
            <button
              key={r.pid_id}
              type="button"
              data-active={isActive}
              onClick={() => goTo(i)}
              className={`shrink-0 px-2.5 py-1.5 rounded-full text-[11px] font-medium transition-all whitespace-nowrap ${
                isActive
                  ? 'bg-primary/20 text-primary border border-primary/30'
                  : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.06] border border-transparent'
              }`}
              title={label + (issueCount > 0 ? ` · ${issueCount} issues` : '')}
            >
              {label}
              {issueCount > 0 && (
                <span className={`ml-1 text-[10px] ${isActive ? 'text-primary/80' : 'text-muted-foreground'}`}>
                  · {issueCount} {issueCount === 1 ? 'issue' : 'issues'}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => goTo(Math.min(results.length - 1, currentIndex + 1))}
        disabled={currentIndex >= results.length - 1}
        className="p-1 rounded-full text-muted-foreground hover:text-foreground hover:bg-white/[0.06] disabled:opacity-30 disabled:cursor-not-allowed transition-all"
        aria-label="Next diagram"
      >
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
