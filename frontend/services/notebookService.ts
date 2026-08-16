import { apiRequest } from './api';
import type {
  NotebookAttempt,
  NotebookAttemptResponse,
  NotebookItem,
  NotebookListResponse,
  PracticeRecommendResponse,
  SubjectCode,
} from '../types';

export async function saveFeedback(body: {
  problem: string;
  helpful: boolean;
  note?: string;
  session_id?: string | null;
  stage?: string | null;
  final_answer?: string | null;
  reply?: string | null;
  subject?: SubjectCode;
}): Promise<{ status: string; message: string; item: NotebookItem }> {
  return apiRequest('/api/feedback', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function fetchNotebook(params: {
  filter?: 'all' | 'wrong' | 'mastered';
  topic?: string;
  limit?: number;
} = {}): Promise<NotebookListResponse> {
  const search = new URLSearchParams();
  if (params.filter) search.set('filter', params.filter);
  if (params.topic) search.set('topic', params.topic);
  if (params.limit) search.set('limit', String(params.limit));
  const query = search.toString();
  return apiRequest<NotebookListResponse>(`/api/notebook${query ? `?${query}` : ''}`);
}

export async function deleteNotebookItem(itemId: string): Promise<void> {
  await apiRequest(`/api/notebook/${itemId}`, { method: 'DELETE' });
}

export async function submitNotebookAttempt(
  itemId: string,
  answer: string,
): Promise<NotebookAttemptResponse> {
  return apiRequest<NotebookAttemptResponse>(`/api/notebook/${itemId}/attempts`, {
    method: 'POST',
    body: JSON.stringify({ answer }),
  });
}

export async function markNotebookMastered(itemId: string): Promise<{ item: NotebookItem }> {
  return apiRequest(`/api/notebook/${itemId}/mastered`, { method: 'POST' });
}

export async function fetchNotebookAttempts(
  itemId: string,
): Promise<{ item: NotebookItem; attempts: NotebookAttempt[] }> {
  return apiRequest(`/api/notebook/${itemId}/attempts`);
}

export async function recommendPractice(body: {
  subject?: SubjectCode;
  problem?: string;
  topic?: string;
  limit?: number;
  exclude?: string[];
} = {}): Promise<PracticeRecommendResponse> {
  return apiRequest<PracticeRecommendResponse>('/api/practice/recommend', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
