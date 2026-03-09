import { create } from 'zustand';
import type { AnalysisRun, Graph, ValidationResult } from '@/types/graph';

export type ValidationResultItem = {
  pid_id: string;
  file_name?: string;
  page_num?: number;
  status: string;
  issues: ValidationResult['issues'];
};

interface PidState {
  currentPidId: string | null;
  graph: Graph | null;
  validation: ValidationResult | null;
  /** When SOP validation returns multiple P&IDs, store them for diagram switcher */
  validationResults: ValidationResultItem[];
  runs: AnalysisRun[];
  selectedNodeId: string | null;
  selectedIssueIndex: number | null;
  highlightedNodes: string[];
  filterType: string | null;
  searchQuery: string;

  setPidId: (id: string) => void;
  setGraph: (graph: Graph) => void;
  setValidation: (result: ValidationResult) => void;
  setValidationResults: (results: ValidationResultItem[]) => void;
  addRun: (run: AnalysisRun) => void;
  setRuns: (runs: AnalysisRun[]) => void;
  updateRun: (pidId: string, patch: Partial<AnalysisRun>) => void;
  selectNode: (id: string | null) => void;
  selectIssue: (index: number | null) => void;
  setHighlightedNodes: (ids: string[]) => void;
  setFilterType: (type: string | null) => void;
  setSearchQuery: (query: string) => void;
}

export const usePidStore = create<PidState>((set) => ({
  currentPidId: null,
  graph: null,
  validation: null,
  validationResults: [],
  runs: [],
  selectedNodeId: null,
  selectedIssueIndex: null,
  highlightedNodes: [],
  filterType: null,
  searchQuery: '',

  setPidId: (id) => set({ currentPidId: id }),
  setGraph: (graph) => set({ graph }),
  setValidation: (result) => set({ validation: result }),
  setValidationResults: (results) => set({ validationResults: results }),
  addRun: (run) =>
    set((s) => {
      const rest = s.runs.filter((r) => r.pid_id !== run.pid_id);
      return { runs: [{ ...(s.runs.find((r) => r.pid_id === run.pid_id) || {}), ...run }, ...rest] };
    }),
  setRuns: (runs) => set({ runs }),
  updateRun: (pidId, patch) =>
    set((s) => ({
      runs: s.runs.map((r) => (r.pid_id === pidId ? { ...r, ...patch } : r)),
    })),
  selectNode: (id) => set({ selectedNodeId: id }),
  selectIssue: (index) => set({ selectedIssueIndex: index }),
  setHighlightedNodes: (ids) => set({ highlightedNodes: ids }),
  setFilterType: (type) => set({ filterType: type }),
  setSearchQuery: (query) => set({ searchQuery: query }),
}));
