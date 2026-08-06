import { apiRequest, consumeSse, getToken } from './api';
import type { ExampleItem, LessonResponse, RecognizeResponse, StreamEvent } from '../types';

export async function fetchExamples(): Promise<ExampleItem[]> {
  return apiRequest<ExampleItem[]>('/api/examples');
}

export async function recognizeImage(file: File): Promise<RecognizeResponse> {
  const form = new FormData();
  form.append('file', file);
  return apiRequest<RecognizeResponse>('/api/recognize', {
    method: 'POST',
    body: form,
  });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiRequest(`/api/session/${sessionId}`, { method: 'DELETE' });
}

export async function streamLesson(
  body: {
    problem: string;
    message?: string;
    stage?: string;
    session_id?: string | null;
    audio_base64?: string | null;
    sample_rate?: number;
  },
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const headers = new Headers({ 'Content-Type': 'application/json' });
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);

  const response = await fetch('/api/lesson/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.error || detail;
    } catch {
      // ignore
    }
    throw new Error(String(detail || '讲解失败'));
  }

  await consumeSse(response, (event) => onEvent(event as StreamEvent));
}

export async function createLesson(body: {
  problem: string;
  message?: string;
  stage?: string;
  session_id?: string | null;
}): Promise<LessonResponse> {
  return apiRequest<LessonResponse>('/api/lesson', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}
