import { forwardRef, ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { LayoutDashboard, GitBranch, ShieldCheck, FileBarChart, Workflow } from 'lucide-react';
import { usePidStore } from '@/store/usePidStore';

const AppLayout = forwardRef<HTMLDivElement, { children: ReactNode }>(({ children }, ref) => {
  const location = useLocation();
  const currentPidId = usePidStore((s) => s.currentPidId);
  const runs = usePidStore((s) => s.runs);
  const pidId = currentPidId ?? runs[0]?.pid_id ?? null;

  const navItems = [
    { path: '/', label: 'Dashboard', icon: LayoutDashboard },
    { path: pidId ? `/graph/${pidId}` : '/', label: 'Graph', icon: GitBranch },
    { path: pidId ? `/validation/${pidId}` : '/', label: 'Validation', icon: ShieldCheck },
    { path: pidId ? `/report/${pidId}` : '/', label: 'Report', icon: FileBarChart },
  ];

  return (
    <div ref={ref} className="flex flex-col h-screen overflow-hidden bg-background">
      {/* Top navbar — floating glass pill */}
      <header className="relative z-50 flex justify-center px-6 pt-4">
        <nav className="glass-strong rounded-full px-1.5 py-1.5 flex items-center gap-0.5 shadow-xl shadow-black/25">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2.5 pl-4 pr-3 py-1">
            <div className="h-7 w-7 rounded-full bg-primary/15 flex items-center justify-center">
              <Workflow className="h-3.5 w-3.5 text-primary" />
            </div>
            <span className="text-[13px] font-semibold text-foreground tracking-[-0.02em]">P&ID Analyzer</span>
          </Link>

          <div className="h-5 w-px bg-white/[0.08] mx-1.5" />

          {/* Nav Items — pill buttons */}
          <div className="flex items-center gap-0.5">
            {navItems.map((item) => {
              const isActive = location.pathname === item.path ||
                (item.path !== '/' && location.pathname.startsWith(item.path.split('/').slice(0, 2).join('/')));
              return (
                <Link
                  key={item.path + (item.path === '/' ? '' : pidId ?? '')}
                  to={item.path}
                  className={`flex items-center gap-2 rounded-full px-4 py-2 text-[13px] font-medium transition-all duration-200 ${
                    isActive
                      ? 'bg-white/[0.1] text-foreground'
                      : 'text-muted-foreground hover:text-foreground hover:bg-white/[0.05]'
                  }`}
                >
                  <item.icon className="h-3.5 w-3.5" />
                  {item.label}
                </Link>
              );
            })}
          </div>

          <div className="h-5 w-px bg-white/[0.08] mx-1.5" />

          {/* Status */}
          <div className="flex items-center gap-1.5 px-4 py-1">
            <div className="h-1.5 w-1.5 rounded-full bg-success animate-pulse" />
            <span className="text-[11px] text-muted-foreground font-medium">Online</span>
          </div>
        </nav>
      </header>

      {/* Main content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {children}
      </main>
    </div>
  );
});

AppLayout.displayName = 'AppLayout';
export default AppLayout;
