import React, { useMemo, useState } from 'react';
import type { AppConfig, AuthMode, User } from '../types';
import { login, register } from '../services/authService';

interface AuthModalProps {
  config: AppConfig | null;
  onSuccess: (user: User) => void;
}

type DemoAccount = { email: string; password: string; label: string };
type DemoKey = 'admin' | 'teacher' | 'student';

const DEMO_FALLBACK: Record<DemoKey, DemoAccount> = {
  admin: { email: 'teacher@demo.local', password: 'demo123', label: '管理员' },
  teacher: { email: 'math.teacher@demo.local', password: 'demo123', label: '教师' },
  student: { email: 'student@demo.local', password: 'demo123', label: '学生' },
};

export default function AuthModal({ config, onSuccess }: AuthModalProps) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [email, setEmail] = useState(DEMO_FALLBACK.admin.email);
  const [password, setPassword] = useState(DEMO_FALLBACK.admin.password);
  const [nickname, setNickname] = useState('');
  const [role, setRole] = useState<'student' | 'teacher'>('student');
  const [grade, setGrade] = useState('grade8');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const demoAccounts = useMemo(() => {
    const map: Record<DemoKey, DemoAccount> = {
      admin: { ...DEMO_FALLBACK.admin },
      teacher: { ...DEMO_FALLBACK.teacher },
      student: { ...DEMO_FALLBACK.student },
    };
    config?.demo_accounts?.forEach((item) => {
      if (item.id === 'admin' || item.id === 'teacher' || item.id === 'student') {
        map[item.id] = {
          ...map[item.id],
          email: item.email || map[item.id].email,
          label: item.label || map[item.id].label,
        };
      }
    });
    return map;
  }, [config]);

  const grades = config?.grades?.length
    ? config.grades
    : [
        { code: 'grade7', name: '初一' },
        { code: 'grade8', name: '初二' },
        { code: 'grade9', name: '初三' },
        { code: 'grade10', name: '高一' },
        { code: 'grade11', name: '高二' },
        { code: 'grade12', name: '高三' },
      ];

  const applyDemo = (id: DemoKey) => {
    const account = demoAccounts[id];
    setMode('login');
    setEmail(account.email);
    setPassword(account.password);
    setError('');
  };

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setLoading(true);
    try {
      const payload =
        mode === 'login'
          ? await login(email.trim(), password)
          : await register({
              email: email.trim(),
              password,
              nickname: nickname.trim(),
              role,
              grade: role === 'student' ? grade : null,
            });
      onSuccess(payload.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败，请重试');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-canvas flex items-center justify-center p-4">
      <div className="w-full max-w-md rounded-2xl border border-line bg-panel shadow-2xl shadow-black/40 overflow-hidden">
        <div className="px-6 pt-6 pb-4 border-b border-line/80">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center font-bold">M</div>
            <div>
              <h1 className="text-lg font-semibold tracking-wide">Math Coach</h1>
              <p className="text-xs text-muted">MiniCPM-o 4.5 · 登录后开始学习</p>
            </div>
          </div>
        </div>

        <div className="px-6 pt-4">
          <div className="grid grid-cols-2 gap-1 p-1 rounded-xl bg-black/30 border border-line">
            <button
              type="button"
              className={`py-2 rounded-lg text-sm transition ${mode === 'login' ? 'bg-blue-600 text-white' : 'text-muted hover:text-white'}`}
              onClick={() => setMode('login')}
            >
              登录
            </button>
            <button
              type="button"
              className={`py-2 rounded-lg text-sm transition ${mode === 'register' ? 'bg-blue-600 text-white' : 'text-muted hover:text-white'}`}
              onClick={() => setMode('register')}
            >
              注册
            </button>
          </div>
          <p className="mt-3 text-xs text-muted leading-5">
            {mode === 'register'
              ? '公开注册仅支持学生或教师。管理员不可公开注册。'
              : '支持管理员 / 教师 / 学生登录。管理员由系统初始化，不可公开注册。'}
          </p>
        </div>

        {mode === 'login' && (
          <div className="px-6 pt-3">
            <p className="text-xs text-muted mb-2">快速填充演示账号</p>
            <div className="flex flex-wrap gap-2">
              {(Object.keys(demoAccounts) as DemoKey[]).map((id) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => applyDemo(id)}
                  className="px-3 py-1.5 rounded-lg border border-line bg-black/20 text-xs text-gray-200 hover:border-blue-500 hover:text-white transition"
                >
                  {demoAccounts[id].label}
                </button>
              ))}
            </div>
          </div>
        )}

        <form className="px-6 py-5 space-y-3" onSubmit={handleSubmit}>
          <label className="block text-xs text-muted">邮箱</label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-xl border border-line bg-black/30 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
            placeholder="teacher@demo.local"
            autoComplete="username"
          />

          {mode === 'register' && (
            <>
              <label className="block text-xs text-muted">昵称</label>
              <input
                type="text"
                required
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                className="w-full rounded-xl border border-line bg-black/30 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
                placeholder="2-32 字"
                autoComplete="nickname"
              />
            </>
          )}

          <label className="block text-xs text-muted">密码</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-xl border border-line bg-black/30 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
            placeholder="至少 8 位，含字母和数字"
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />

          {mode === 'register' && (
            <>
              <label className="block text-xs text-muted">注册角色</label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value as 'student' | 'teacher')}
                className="w-full rounded-xl border border-line bg-black/30 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
              >
                <option value="student">学生</option>
                <option value="teacher">教师</option>
              </select>

              {role === 'student' && (
                <>
                  <label className="block text-xs text-muted">年级（学生可选）</label>
                  <select
                    value={grade}
                    onChange={(e) => setGrade(e.target.value)}
                    className="w-full rounded-xl border border-line bg-black/30 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
                  >
                    {grades.map((item) => (
                      <option key={item.code} value={item.code}>
                        {item.name}
                      </option>
                    ))}
                  </select>
                </>
              )}
            </>
          )}

          {error && (
            <div className="rounded-xl border border-red-500/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-60 disabled:cursor-not-allowed py-2.5 text-sm font-medium transition"
          >
            {loading ? '处理中…' : mode === 'login' ? '登录' : '注册并登录'}
          </button>
        </form>

        <div className="px-6 pb-5 text-xs text-muted">
          演示默认密码：demo123 · 账号数据支持 SQLite / MySQL
        </div>
      </div>
    </div>
  );
}
