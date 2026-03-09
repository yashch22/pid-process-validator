import axios from 'axios';
import type { Graph, PidUploadResponse, ValidationResult } from '@/types/graph';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
});

export const uploadPid = async (file: File): Promise<PidUploadResponse> => {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/upload/pid', formData);
  return data;
};

export const getGraph = async (pidId: string): Promise<Graph> => {
  const { data } = await api.get(`/graph/${pidId}`);
  return data;
};

export const uploadSop = async (file: File): Promise<{ sop_id: string }> => {
  const formData = new FormData();
  formData.append('file', file);
  const { data } = await api.post('/upload/sop', formData);
  return data;
};

/** Validate SOP against matching P&IDs (searches vector DB, validates each). */
export const validateSopById = async (sopId: string, topK = 10): Promise<{
  sop_id: string;
  matches: Array<{ pid_id: string; file_name?: string; page_num?: number; distance?: number }>;
  results: Array<{ pid_id: string; file_name?: string; page_num?: number; status: string; issues: ValidationResult['issues'] }>;
}> => {
  const { data } = await api.post(`/validate/sop/${sopId}?top_k=${topK}`);
  return data;
};

/** Get latest validation for a P&ID (from DB or run fresh if SOP linked). */
export const getValidation = async (pidId: string): Promise<ValidationResult> => {
  const { data } = await api.get(`/validation/${pidId}`);
  return data;
};

/** Get all validation results for an SOP (one per linked P&ID). SOP is not bound to a single pid. */
export const getValidationBySop = async (sopId: string): Promise<{
  sop_id: string;
  sop_file_name?: string;
  results: Array<{ pid_id: string; file_name?: string; page_num?: number; status: string; issues: ValidationResult['issues'] }>;
}> => {
  const { data } = await api.get(`/validation/sop/${sopId}`);
  return data;
};

/** Legacy: run validation for pid_id (uses SOP linked to that P&ID if any). */
export const validateSop = async (pidId: string): Promise<ValidationResult> => {
  const { data } = await api.post(`/validate/${pidId}`);
  return data;
};

export const listSops = async (): Promise<{ sops: Array<{ sop_id: string; file_name?: string; created_at: string }> }> => {
  const { data } = await api.get('/sops');
  return data;
};

export const listPids = async (limit = 50): Promise<{
  pids: Array<{ pid_id: string; filename: string; sopFilename?: string; timestamp: string; status: string; issueCount?: number }>;
}> => {
  const { data } = await api.get(`/pids?limit=${limit}`);
  return data;
};

export default api;
