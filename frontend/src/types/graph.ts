export type ComponentType = 'pump' | 'valve' | 'sensor' | 'tank' | 'pipe' | 'compressor';

export type GraphNode = {
  id: string;
  type: ComponentType;
  label: string;
  attributes: Record<string, unknown>;
};

export type GraphEdge = {
  source: string;
  target: string;
};

export type Graph = {
  nodes: GraphNode[];
  edges: GraphEdge[];
};

export type IssueType = 'missing_component' | 'connection_mismatch' | 'attribute_mismatch' | 'unexpected_component' | 'validation_skipped';

export type ValidationIssue = {
  type: IssueType;
  component?: string;
  description: string;
  severity?: 'error' | 'warning' | 'info';
  relatedNodes?: string[];
};

export type ValidationResult = {
  status: 'completed' | 'pending' | 'failed';
  issues: ValidationIssue[];
};

export type PidUploadResponse = {
  pid_id: string;
};

export type AnalysisRun = {
  pid_id: string;
  filename: string;
  sopFilename?: string;
  timestamp: string;
  status: 'uploaded' | 'graph_ready' | 'sop_uploaded' | 'validated';
  issueCount?: number;
};

/** Unified recent item: P&ID or SOP document */
export type RecentItem =
  | { type: 'pid'; id: string; pid_id: string; filename: string; sopFilename?: string; timestamp: string; status: string; issueCount?: number }
  | { type: 'sop'; id: string; sop_id: string; filename: string; timestamp: string };
