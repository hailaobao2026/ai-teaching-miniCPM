import { apiRequest, setToken } from './api';
import type { AppConfig, AuthResponse, User } from '../types';

export async function fetchConfig(): Promise<AppConfig> {
  return apiRequest<AppConfig>('/api/config');
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const payload = await apiRequest<AuthResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  });
  setToken(payload.token);
  return payload;
}

export async function register(input: {
  email: string;
  password: string;
  nickname: string;
  role: 'student' | 'teacher';
  grade?: string | null;
}): Promise<AuthResponse> {
  const payload = await apiRequest<AuthResponse>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(input),
  });
  setToken(payload.token);
  return payload;
}

export async function fetchMe(): Promise<User> {
  const payload = await apiRequest<{ user: User }>('/api/auth/me');
  return payload.user;
}

export async function logout(): Promise<void> {
  try {
    await apiRequest('/api/auth/logout', { method: 'POST' });
  } finally {
    setToken(null);
  }
}

export async function updateProfile(input: {
  nickname?: string;
  grade?: string | null;
}): Promise<User> {
  const payload = await apiRequest<{ user: User }>('/api/me/profile', {
    method: 'PATCH',
    body: JSON.stringify(input),
  });
  return payload.user;
}
