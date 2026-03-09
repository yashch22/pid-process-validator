import type { AnalysisRun, Graph, ValidationResult } from '@/types/graph';

export const mockGraph: Graph = {
  nodes: [
    { id: 'pump_1', type: 'pump', label: 'P-101', attributes: { pressure: '10 bar', flow_rate: '150 L/min', rpm: '3600' } },
    { id: 'pump_2', type: 'pump', label: 'P-102', attributes: { pressure: '8 bar', flow_rate: '120 L/min', rpm: '3000' } },
    { id: 'valve_1', type: 'valve', label: 'V-201', attributes: { type: 'Gate', size: '4"', state: 'Open' } },
    { id: 'valve_2', type: 'valve', label: 'V-202', attributes: { type: 'Globe', size: '3"', state: 'Closed' } },
    { id: 'valve_3', type: 'valve', label: 'V-203', attributes: { type: 'Check', size: '4"', state: 'Open' } },
    { id: 'tank_1', type: 'tank', label: 'T-101', attributes: { capacity: '5000 L', material: 'SS316', level: '72%' } },
    { id: 'tank_2', type: 'tank', label: 'T-102', attributes: { capacity: '3000 L', material: 'CS', level: '45%' } },
    { id: 'sensor_1', type: 'sensor', label: 'PT-301', attributes: { type: 'Pressure', range: '0-20 bar', output: '4-20 mA' } },
    { id: 'sensor_2', type: 'sensor', label: 'FT-301', attributes: { type: 'Flow', range: '0-200 L/min', output: '4-20 mA' } },
    { id: 'sensor_3', type: 'sensor', label: 'LT-301', attributes: { type: 'Level', range: '0-100%', output: '4-20 mA' } },
    { id: 'compressor_1', type: 'compressor', label: 'C-101', attributes: { power: '75 kW', type: 'Centrifugal' } },
    { id: 'pipe_1', type: 'pipe', label: 'L-001', attributes: { diameter: '4"', material: 'SS304' } },
    { id: 'pipe_2', type: 'pipe', label: 'L-002', attributes: { diameter: '3"', material: 'CS' } },
  ],
  edges: [
    { source: 'tank_1', target: 'valve_1' },
    { source: 'valve_1', target: 'pump_1' },
    { source: 'pump_1', target: 'sensor_1' },
    { source: 'sensor_1', target: 'pipe_1' },
    { source: 'pipe_1', target: 'valve_2' },
    { source: 'valve_2', target: 'tank_2' },
    { source: 'tank_2', target: 'valve_3' },
    { source: 'valve_3', target: 'pump_2' },
    { source: 'pump_2', target: 'sensor_2' },
    { source: 'sensor_2', target: 'compressor_1' },
    { source: 'compressor_1', target: 'pipe_2' },
    { source: 'tank_1', target: 'sensor_3' },
  ],
};

export const mockValidation: ValidationResult = {
  status: 'completed',
  issues: [
    { type: 'missing_component', component: 'Valve V-204', description: 'Valve referenced in SOP Step 3 but not present in P&ID', severity: 'error', relatedNodes: ['valve_2'] },
    { type: 'connection_mismatch', component: 'P-101 → T-102', description: 'SOP expects Pump P-101 to connect directly to Tank T-102, but graph shows intermediate components', severity: 'error', relatedNodes: ['pump_1', 'tank_2'] },
    { type: 'attribute_mismatch', component: 'P-101', description: 'SOP specifies pressure of 12 bar, but P&ID shows 10 bar', severity: 'warning', relatedNodes: ['pump_1'] },
    { type: 'unexpected_component', component: 'C-101', description: 'Compressor C-101 present in P&ID but not referenced in any SOP procedure', severity: 'info', relatedNodes: ['compressor_1'] },
  ],
};

export const mockRuns: AnalysisRun[] = [
  { pid_id: 'demo-001', filename: 'process_unit_A.pdf', sopFilename: 'SOP_startup.docx', timestamp: '2026-03-08T10:23:00Z', status: 'validated', issueCount: 4 },
  { pid_id: 'demo-002', filename: 'cooling_system.pdf', timestamp: '2026-03-07T15:45:00Z', status: 'graph_ready', issueCount: 0 },
  { pid_id: 'demo-003', filename: 'reactor_feed.pdf', sopFilename: 'SOP_reactor.docx', timestamp: '2026-03-06T09:12:00Z', status: 'validated', issueCount: 2 },
];
