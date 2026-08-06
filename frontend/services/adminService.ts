import { apiRequest } from './api';
import type { AdminStats, AdminUser, UserRole, UserStatus } from '../types';

export async function fetchAdminStats(): Promise<AdminStats> {
  return apiRequest<AdminStats>('/api/admin/stats');
}

export async function listUsers(params: {
  role?: string;
  status?: string;
  q?: string;
  page?: number;
  limit?: number;
} = {}): Promise<AdminUser[]> {
  const search = new URLSearchParams();
  if (params.role) search.set('role', params.role);
  if (params.status) search.set('status', params.status);
  if (params.q) search.set('q', params.q);
  if (params.page) search.set('page', String(params.page));
  if (params.limit) search.set('limit', String(params.limit));
  const query = search.toString();
  return apiRequest<AdminUser[]>(`/api/admin/users${query ? `?${query}` : ''}`);
}

export async function updateUser(
  userId: string,
  patch: {
    role?: UserRole;
    status?: UserStatus;
    nickname?: string;
    password?: string;
  },
): Promise<AdminUser> {
  const payload = await apiRequest<{ user: AdminUser }>(`/api/admin/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  return payload.user;
}
