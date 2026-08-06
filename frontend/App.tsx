import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AuthModal from './components/AuthModal';
import {
  AdminIcon,
  HistoryIcon,
  HomeIcon,
  LogoutIcon,
  MicIcon,
  RefreshIcon,
  SendIcon,
  SparklesIcon,
  UploadIcon,
} from './components/Icons';
import { fetchAdminStats, listUsers, updateUser } from './services/adminService';
import { getToken, setUnauthorizedHandler } from './services/api';
import { fetchConfig, fetchMe, logout as logoutRequest } from './services/authService';
import {
  deleteSession,
  fetchExamples,
  recognizeImage,
  streamLesson,
} from './services/lessonService';
import type {
  AdminStats,
  AdminUser,
  Annotation,
  AppConfig,
  AppView,
  ChatMessage,
  ExampleItem,
  LessonResponse,
  LessonStage,
  SavedLesson,
  User,
  UserRole,
  UserStatus,
} from './types';

const PROGRESS_KEY = 'mathCoachProgress';
const SAVED_KEY = 'mathCoachSaved';

function roleLabel(role?: string | null) {
  return ({ admin: '管理员', teacher: '教师', student: '学生' } as Record<string, string>)[role || ''] || role || '—';
}

function toast(message: string) {
  const existing = document.getElementById('math-coach-toast');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.id = 'math-coach-toast';
  el.textContent = message;
  el.className =
    'fixed bottom-6 left-1/2 -translate-x-1/2 z-[100] px-4 py-2 rounded-full bg-gray-900 border border-line text-sm text-white shadow-xl';
  document.body.appendChild(el);
  window.setTimeout(() => el.remove(), 2400);
}

function loadSaved(): SavedLesson[] {
  try {
    return JSON.parse(localStorage.getItem(SAVED_KEY) || '[]') as SavedLesson[];
  } catch {
    return [];
  }
}

function saveSaved(items: SavedLesson[]) {
  localStorage.setItem(SAVED_KEY, JSON.stringify(items.slice(0, 30)));
}

function playAudio(base64: string, mime = 'audio/wav') {
  const audio = new Audio(`data:${mime};base64,${base64}`);
  audio.play().catch(() => undefined);
}

function SidebarItem({
  active,
  label,
  icon,
  onClick,
}: {
  active: boolean;
  label: string;
  icon: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${
        active ? 'bg-blue-600/20 text-blue-300 border border-blue-500/30' : 'text-gray-300 hover:bg-white/5 border border-transparent'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function AnnotationCanvas({
  imageUrl,
  annotations,
}: {
  imageUrl: string | null;
  annotations: Annotation[];
}) {
  const imgRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const img = imgRef.current;
    const canvas = canvasRef.current;
    if (!img || !canvas || !imageUrl || !annotations.length) {
      if (canvas) {
        const ctx = canvas.getContext('2d');
        ctx?.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }

    const draw = () => {
      const width = img.clientWidth;
      const height = img.clientHeight;
      if (!width || !height) return;
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      ctx.clearRect(0, 0, width, height);
      ctx.strokeStyle = '#22c55e';
      ctx.lineWidth = 2;
      annotations.forEach((box) => {
        ctx.strokeRect(box.x * width, box.y * height, box.width * width, box.height * height);
      });
    };

    if (img.complete) draw();
    else img.onload = draw;
    window.addEventListener('resize', draw);
    return () => window.removeEventListener('resize', draw);
  }, [imageUrl, annotations]);

  if (!imageUrl) return null;

  return (
    <div className="relative mt-3 rounded-xl overflow-hidden border border-line bg-black/30">
      <img ref={imgRef} src={imageUrl} alt="题目图片预览" className="block w-full max-h-72 object-contain" />
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full pointer-events-none" />
      {annotations.length > 0 && (
        <div className="absolute left-2 bottom-2 text-[11px] px-2 py-1 rounded-md bg-black/70 text-green-300">
          已标注 {annotations.length} 个区域
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [bootstrapping, setBootstrapping] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [view, setView] = useState<AppView>('workspace');

  const [problem, setProblem] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [stage, setStage] = useState<LessonStage>('confirm');
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [lesson, setLesson] = useState<LessonResponse | null>(null);
  const [streamText, setStreamText] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [message, setMessage] = useState('');
  const [sourceTab, setSourceTab] = useState<'text' | 'upload' | 'examples'>('text');
  const [examples, setExamples] = useState<ExampleItem[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [questionState, setQuestionState] = useState('等待题目');
  const [progress, setProgress] = useState(Number(localStorage.getItem(PROGRESS_KEY) || 0));
  const [saved, setSaved] = useState<SavedLesson[]>(() => loadSaved());
  const [recording, setRecording] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('按住说话');
  const [listeningBadge, setListeningBadge] = useState('待机');

  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [adminRole, setAdminRole] = useState('');
  const [adminStatus, setAdminStatus] = useState('');
  const [adminQuery, setAdminQuery] = useState('');
  const [adminLoading, setAdminLoading] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const isAdmin = user?.role === 'admin';
  const mode = config?.mode || 'mock';

  const clearSession = useCallback(() => {
    setUser(null);
    setView('workspace');
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      clearSession();
      toast('登录已失效，请重新登录');
    });
    return () => setUnauthorizedHandler(null);
  }, [clearSession]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const cfg = await fetchConfig();
        if (!cancelled) setConfig(cfg);
      } catch {
        // config is public; ignore bootstrap failures
      }

      if (!getToken()) {
        if (!cancelled) setBootstrapping(false);
        return;
      }

      try {
        const me = await fetchMe();
        if (!cancelled) setUser(me);
      } catch {
        // token invalid
      } finally {
        if (!cancelled) setBootstrapping(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!user) return;
    fetchExamples()
      .then(setExamples)
      .catch(() => setExamples([]));
  }, [user]);

  const loadAdmin = useCallback(async () => {
    if (!isAdmin) return;
    setAdminLoading(true);
    try {
      const [stats, users] = await Promise.all([
        fetchAdminStats(),
        listUsers({
          role: adminRole || undefined,
          status: adminStatus || undefined,
          q: adminQuery.trim() || undefined,
        }),
      ]);
      setAdminStats(stats);
      setAdminUsers(users);
    } catch (err) {
      toast(err instanceof Error ? err.message : '加载管理后台失败');
    } finally {
      setAdminLoading(false);
    }
  }, [adminQuery, adminRole, adminStatus, isAdmin]);

  useEffect(() => {
    if (view === 'admin' && isAdmin) {
      void loadAdmin();
    }
  }, [view, isAdmin, loadAdmin]);

  const pageTitle = useMemo(() => {
    if (view === 'admin') return '管理后台';
    if (view === 'history') return '本地学习记录';
    return '今天，从一道题开始。';
  }, [view]);

  const handleLogout = async () => {
    try {
      await logoutRequest();
    } catch {
      // ignore
    }
    clearSession();
    toast('已退出登录');
  };

  const updateProgressCount = (next: number) => {
    const value = Math.min(3, next);
    setProgress(value);
    localStorage.setItem(PROGRESS_KEY, String(value));
  };

  const appendHistory = (role: 'user' | 'assistant', text: string) => {
    setHistory((prev) => [{ role, text }, ...prev]);
  };

  const sendLesson = async (
    userMessage: string,
    nextStage: LessonStage | string,
    audioBase64?: string | null,
    sampleRate = 16000,
  ) => {
    const currentProblem = problem.trim();
    if (!currentProblem) {
      toast('请先输入或识别题面');
      return;
    }
    if (streaming) return;

    setStreaming(true);
    setStreamText('');
    setQuestionState(nextStage === 'confirm' ? '确认题面中…' : '讲解生成中…');
    if (userMessage) appendHistory('user', userMessage);

    try {
      const streamState: { lesson: LessonResponse | null; source: string } = {
        lesson: null,
        source: mode,
      };

      await streamLesson(
        {
          problem: currentProblem,
          message: userMessage,
          stage: nextStage,
          session_id: sessionId,
          audio_base64: audioBase64 || null,
          sample_rate: sampleRate,
        },
        (event) => {
          if (event.type === 'session' && event.session_id) {
            setSessionId(String(event.session_id));
          }
          if (event.type === 'text_delta') {
            const delta = String(event.delta || event.text || '');
            setStreamText((prev) => prev + delta);
            if (event.source) streamState.source = String(event.source);
          }
          if (event.type === 'lesson' && event.lesson) {
            streamState.lesson = event.lesson as LessonResponse;
            if (streamState.lesson.session_id) setSessionId(streamState.lesson.session_id);
          }
          if (event.type === 'error') {
            throw new Error(String(event.error || '讲解失败'));
          }
        },
      );

      const latestLesson = streamState.lesson;
      if (!latestLesson) throw new Error('未收到讲解结果');
      setLesson(latestLesson);
      setStreamText('');
      setConfirmed(true);
      setStage((latestLesson.stage as LessonStage) || (nextStage as LessonStage) || 'hint');
      setQuestionState(latestLesson.final_answer ? '完整解析已生成' : '可继续追问');
      appendHistory('assistant', latestLesson.reply);
      if (latestLesson.audio_base64) playAudio(latestLesson.audio_base64, latestLesson.audio_mime || 'audio/wav');
      if ((latestLesson.stage === 'explain' || nextStage === 'explain') && latestLesson.final_answer) {
        updateProgressCount(progress + 1);
      }
      if (latestLesson.source) {
        setConfig((prev) => (prev ? { ...prev, mode: latestLesson.source || prev.mode } : prev));
      } else if (streamState.source) {
        setConfig((prev) => (prev ? { ...prev, mode: streamState.source } : prev));
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : '讲解失败');
    } finally {
      setStreaming(false);
      setVoiceStatus('按住说话');
      setListeningBadge('待机');
    }
  };

  const confirmProblem = async () => {
    const text = problem.trim();
    if (!text) return toast('请先输入题面');
    setProblem(text);
    await sendLesson('请先确认题面，并给一个引导提示。', 'confirm');
  };

  const handleRecognize = async (file: File) => {
    const url = URL.createObjectURL(file);
    setImageUrl(url);
    setSourceTab('upload');
    setQuestionState('识题中…');
    try {
      const result = await recognizeImage(file);
      setProblem(result.problem || '');
      setAnnotations(result.annotations || []);
      setQuestionState(result.problem ? '题面已识别，请确认' : '未识别到题面');
      toast('识题完成');
    } catch (err) {
      toast(err instanceof Error ? err.message : '识别失败');
      setQuestionState('识题失败');
    }
  };

  const saveCurrent = () => {
    if (!problem.trim() || !lesson) return toast('还没有可保存的讲解');
    const item: SavedLesson = {
      id: crypto.randomUUID(),
      problem: problem.trim(),
      reply: lesson.reply,
      final_answer: lesson.final_answer,
      saved_at: new Date().toISOString(),
    };
    const next = [item, ...saved];
    setSaved(next);
    saveSaved(next);
    toast('已保存到浏览器本地');
  };

  const resetAll = async () => {
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // ignore
      }
    }
    setSessionId(null);
    setProblem('');
    setConfirmed(false);
    setStage('confirm');
    setHistory([]);
    setLesson(null);
    setStreamText('');
    setAnnotations([]);
    setImageUrl(null);
    setMessage('');
    setQuestionState('等待题目');
    toast('已重新开始');
  };

  const startRecording = async () => {
    if (recording || streaming) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      toast('当前浏览器不支持录音');
      return;
    }
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = mediaStream;
      const recorder = new MediaRecorder(mediaStream);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = async () => {
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' });
        const buffer = await blob.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = '';
        bytes.forEach((b) => {
          binary += String.fromCharCode(b);
        });
        const base64 = btoa(binary);
        setListeningBadge('待机');
        setVoiceStatus('语音已发送，正在讲解');
        await sendLesson('请根据我的语音继续讲解', stage || 'hint', base64, 16000);
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecording(true);
      setListeningBadge('聆听中');
      setVoiceStatus('正在听你说…');
    } catch {
      toast('无法打开麦克风');
    }
  };

  const stopRecording = () => {
    if (!recording || !recorderRef.current) return;
    setRecording(false);
    recorderRef.current.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
    recorderRef.current = null;
    streamRef.current = null;
  };

  const handleAdminSave = async (userId: string, role: UserRole, status: UserStatus) => {
    try {
      await updateUser(userId, { role, status });
      toast('用户已更新');
      await loadAdmin();
    } catch (err) {
      toast(err instanceof Error ? err.message : '更新失败');
    }
  };

  if (bootstrapping) {
    return (
      <div className="min-h-screen bg-canvas flex items-center justify-center text-muted text-sm">
        正在加载 Math Coach…
      </div>
    );
  }

  if (!user) {
    return (
      <AuthModal
        config={config}
        onSuccess={(nextUser) => {
          setUser(nextUser);
          setView('workspace');
          toast(`欢迎，${nextUser.nickname}`);
        }}
      />
    );
  }

  const stageIndex = stage === 'confirm' ? 0 : stage === 'hint' ? 1 : 2;

  return (
    <div className="min-h-screen bg-canvas text-white flex">
      <aside className="hidden md:flex w-64 shrink-0 border-r border-line bg-[#0c0e16] flex-col p-4 gap-4">
        <div className="flex items-center gap-2 px-1">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center text-xs font-bold">
            M
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide">math / coach</div>
            <div className="text-[11px] text-muted">全模态数学课堂</div>
          </div>
        </div>

        <nav className="space-y-1">
          <SidebarItem
            active={view === 'workspace'}
            label="当前学习"
            icon={<HomeIcon active={view === 'workspace'} />}
            onClick={() => setView('workspace')}
          />
          <SidebarItem
            active={view === 'history'}
            label="本地记录"
            icon={<HistoryIcon active={view === 'history'} />}
            onClick={() => setView('history')}
          />
          {isAdmin && (
            <SidebarItem
              active={view === 'admin'}
              label="管理后台"
              icon={<AdminIcon active={view === 'admin'} />}
              onClick={() => setView('admin')}
            />
          )}
        </nav>

        <div className="rounded-2xl border border-line bg-black/20 p-3">
          <div className="text-[11px] text-muted">今日进度</div>
          <div className="mt-1 text-lg font-semibold">
            {Math.min(progress, 3)} / 3
          </div>
          <div className="mt-2 h-1.5 rounded-full bg-white/10 overflow-hidden">
            <div
              className="progress-fill h-full bg-gradient-to-r from-blue-500 to-violet-500"
              style={{ width: `${(Math.min(progress, 3) / 3) * 100}%` }}
            />
          </div>
          <p className="mt-2 text-[11px] text-muted">完成一题后会自动更新</p>
        </div>

        <div className="mt-auto space-y-3">
          <div className="flex items-center gap-3 rounded-2xl border border-line bg-black/20 p-3">
            <div className="w-10 h-10 rounded-full bg-blue-600/30 border border-blue-500/40 flex items-center justify-center font-semibold">
              {(user.nickname || '?').slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0">
              <div className="text-sm font-medium truncate">{user.nickname}</div>
              <div className="text-[11px] text-muted">{roleLabel(user.role)}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => void handleLogout()}
            className="w-full flex items-center justify-center gap-2 rounded-xl border border-line bg-white/5 hover:bg-white/10 py-2 text-sm transition"
          >
            <LogoutIcon />
            退出登录
          </button>
          <div className="text-[11px] text-muted px-1">MiniCPM-o 4.5 · turn-based</div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <header className="border-b border-line bg-[#0c0e16]/70 backdrop-blur sticky top-0 z-20">
          <div className="px-4 md:px-6 py-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted">初中数学 · 引导式学习</p>
              <h1 className="text-xl md:text-2xl font-semibold mt-1">{pageTitle}</h1>
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span
                className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${
                  mode === 'minicpm'
                    ? 'border-green-500/40 bg-green-500/10 text-green-300'
                    : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                }`}
              >
                <span className={`w-1.5 h-1.5 rounded-full ${mode === 'minicpm' ? 'bg-green-400' : 'bg-amber-300'}`} />
                {mode === 'minicpm' ? 'MiniCPM-o 已连接' : 'Mock 演示模式'}
              </span>
              {view !== 'admin' && (
                <>
                  <button
                    type="button"
                    onClick={saveCurrent}
                    className="rounded-xl border border-line bg-white/5 hover:bg-white/10 px-3 py-1.5 text-xs transition"
                  >
                    保存记录
                  </button>
                  <button
                    type="button"
                    onClick={() => void resetAll()}
                    className="rounded-xl border border-line bg-white/5 hover:bg-white/10 px-3 py-1.5 text-xs transition"
                  >
                    重新开始
                  </button>
                </>
              )}
              <button
                type="button"
                className="md:hidden rounded-xl border border-line bg-white/5 px-3 py-1.5 text-xs"
                onClick={() => void handleLogout()}
              >
                退出
              </button>
            </div>
          </div>
          <div className="md:hidden px-4 pb-3 flex gap-2 overflow-x-auto">
            <button type="button" onClick={() => setView('workspace')} className={`px-3 py-1.5 rounded-lg text-xs border ${view === 'workspace' ? 'border-blue-500 text-blue-300' : 'border-line text-muted'}`}>当前学习</button>
            <button type="button" onClick={() => setView('history')} className={`px-3 py-1.5 rounded-lg text-xs border ${view === 'history' ? 'border-blue-500 text-blue-300' : 'border-line text-muted'}`}>本地记录</button>
            {isAdmin && (
              <button type="button" onClick={() => setView('admin')} className={`px-3 py-1.5 rounded-lg text-xs border ${view === 'admin' ? 'border-amber-500 text-amber-300' : 'border-line text-muted'}`}>管理后台</button>
            )}
          </div>
        </header>

        <div className="flex-1 overflow-auto p-4 md:p-6">
          {(view === 'workspace' || view === 'history') && (
            <div className="grid xl:grid-cols-[360px_minmax(0,1fr)_300px] gap-4">
              <section className="rounded-2xl border border-line bg-panel p-4 space-y-4">
                <div className="flex items-center justify-between">
                  <h2 className="text-sm font-semibold">题目输入</h2>
                  <span className="text-[11px] text-muted">{questionState}</span>
                </div>

                <div className="grid grid-cols-3 gap-1 p-1 rounded-xl bg-black/30 border border-line">
                  {([
                    ['text', '文本'],
                    ['upload', '拍照'],
                    ['examples', '例题'],
                  ] as const).map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setSourceTab(id)}
                      className={`py-1.5 rounded-lg text-xs transition ${
                        sourceTab === id ? 'bg-blue-600 text-white' : 'text-muted hover:text-white'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {sourceTab === 'text' && (
                  <textarea
                    value={problem}
                    onChange={(e) => setProblem(e.target.value)}
                    rows={8}
                    placeholder="粘贴或输入数学题面…"
                    className="w-full rounded-xl border border-line bg-black/30 px-3 py-3 text-sm outline-none focus:border-blue-500 resize-y min-h-[160px]"
                  />
                )}

                {sourceTab === 'upload' && (
                  <div>
                    <label className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-black/20 px-4 py-8 cursor-pointer hover:border-blue-500 transition">
                      <UploadIcon />
                      <span className="text-sm">上传题目图片</span>
                      <span className="text-[11px] text-muted">支持常见图片格式</span>
                      <input
                        type="file"
                        accept="image/*"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) void handleRecognize(file);
                        }}
                      />
                    </label>
                    <AnnotationCanvas imageUrl={imageUrl} annotations={annotations} />
                    {imageUrl && (
                      <button
                        type="button"
                        className="mt-2 text-xs text-muted hover:text-white"
                        onClick={() => {
                          setImageUrl(null);
                          setAnnotations([]);
                        }}
                      >
                        移除图片
                      </button>
                    )}
                    <textarea
                      value={problem}
                      onChange={(e) => setProblem(e.target.value)}
                      rows={4}
                      placeholder="识别结果可在此修改…"
                      className="mt-3 w-full rounded-xl border border-line bg-black/30 px-3 py-3 text-sm outline-none focus:border-blue-500"
                    />
                  </div>
                )}

                {sourceTab === 'examples' && (
                  <div className="space-y-2 max-h-[360px] overflow-auto pr-1">
                    {examples.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => {
                          setProblem(item.problem);
                          setAnnotations([]);
                          setSourceTab('text');
                          setQuestionState('已加载例题');
                        }}
                        className="w-full text-left rounded-xl border border-line bg-black/20 hover:border-blue-500 hover:bg-blue-500/5 px-3 py-3 transition"
                      >
                        <div className="text-sm font-medium">{item.title}</div>
                        <div className="mt-1 text-xs text-muted line-clamp-2">{item.problem}</div>
                      </button>
                    ))}
                    {!examples.length && <p className="text-xs text-muted">暂无例题</p>}
                  </div>
                )}

                <button
                  type="button"
                  disabled={streaming}
                  onClick={() => void confirmProblem()}
                  className="w-full rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-60 py-2.5 text-sm font-medium transition flex items-center justify-center gap-2"
                >
                  <SparklesIcon />
                  确认题面并开始
                </button>
              </section>

              <section className="rounded-2xl border border-line bg-panel p-4 flex flex-col min-h-[560px]">
                <div className="flex items-center justify-between gap-3 mb-4">
                  <div className="flex items-center gap-2 text-xs text-muted">
                    {['确认题面', '引导提示', '完整解析'].map((label, index) => (
                      <React.Fragment key={label}>
                        <span
                          className={`${
                            index < stageIndex
                              ? 'text-green-300'
                              : index === stageIndex
                                ? 'text-blue-300'
                                : 'text-muted'
                          }`}
                        >
                          {label}
                        </span>
                        {index < 2 && <span className="text-line">/</span>}
                      </React.Fragment>
                    ))}
                  </div>
                  <span className="text-[11px] text-muted">
                    置信度 {Math.round((lesson?.confidence || 0) * 100)}%
                  </span>
                </div>

                <div className="flex-1 overflow-auto rounded-xl border border-line bg-black/20 p-4">
                  {streaming && streamText && (
                    <div>
                      <div className="text-[11px] text-muted mb-2">AI 老师 · 生成中</div>
                      <p className="text-sm leading-7 whitespace-pre-wrap">
                        {streamText}
                        <span className="stream-cursor">|</span>
                      </p>
                      <p className="mt-3 text-xs text-muted">正在生成分步讲解…</p>
                    </div>
                  )}

                  {!streaming && lesson && (
                    <div className="space-y-4">
                      <div className="text-[11px] text-muted">
                        AI 老师 · {lesson.source === 'minicpm' ? 'MiniCPM-o 4.5' : 'Mock 演示'}
                      </div>
                      <p className="text-sm leading-7 whitespace-pre-wrap">{lesson.reply}</p>
                      <div className="space-y-2">
                        {(lesson.steps || []).map((step, index) => (
                          <div
                            key={`${step.title}-${index}`}
                            className={`rounded-xl border px-3 py-3 ${
                              step.state === 'locked'
                                ? 'border-line/60 bg-black/10 opacity-60'
                                : 'border-line bg-black/20'
                            }`}
                          >
                            <div className="flex gap-3">
                              <div className="w-6 h-6 rounded-full bg-blue-600/20 text-blue-300 text-xs flex items-center justify-center shrink-0">
                                {index + 1}
                              </div>
                              <div>
                                <div className="text-sm font-medium">{step.title}</div>
                                <p className="mt-1 text-xs text-muted leading-6 whitespace-pre-wrap">{step.body}</p>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                      {lesson.final_answer && (
                        <div className="rounded-xl border border-green-500/30 bg-green-500/10 px-3 py-3">
                          <div className="text-[11px] text-green-300">完整解析 · 最终答案</div>
                          <div className="mt-1 text-sm font-semibold">{lesson.final_answer}</div>
                        </div>
                      )}
                      <p className="text-xs text-muted">
                        <strong className="text-gray-200">下一步：</strong>
                        {lesson.next_question || '你想继续吗？'}
                      </p>
                      {!lesson.final_answer && (
                        <button
                          type="button"
                          disabled={streaming}
                          onClick={() => void sendLesson('请给出完整、可核验的分步解析。', 'explain')}
                          className="w-full rounded-xl border border-line bg-white/5 hover:bg-white/10 py-2 text-sm"
                        >
                          查看完整解析
                        </button>
                      )}
                    </div>
                  )}

                  {!streaming && !lesson && (
                    <div className="h-full min-h-[280px] flex flex-col items-center justify-center text-center px-6">
                      <div className="w-14 h-14 rounded-full bg-blue-600/15 border border-blue-500/30 flex items-center justify-center text-xl text-blue-300 mb-3">
                        ?
                      </div>
                      <h3 className="text-base font-medium">先确认题面</h3>
                      <p className="mt-2 text-sm text-muted">我会先给提示，再按你的节奏展开步骤。</p>
                    </div>
                  )}
                </div>

                <div className="mt-4 flex gap-2">
                  <input
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        const text = message.trim();
                        if (!text || streaming) return;
                        setMessage('');
                        void sendLesson(text, confirmed ? stage || 'hint' : 'hint');
                      }
                    }}
                    placeholder={confirmed ? '继续追问，例如：这一步为什么成立？' : '先确认题面后再追问'}
                    className="flex-1 rounded-xl border border-line bg-black/30 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
                  />
                  <button
                    type="button"
                    disabled={streaming}
                    onClick={() => {
                      const text = message.trim();
                      if (!text) return;
                      setMessage('');
                      void sendLesson(text, confirmed ? stage || 'hint' : 'hint');
                    }}
                    className="rounded-xl bg-blue-600 hover:bg-blue-500 disabled:opacity-60 px-3 text-sm flex items-center gap-1"
                  >
                    <SendIcon />
                    发送
                  </button>
                </div>
              </section>

              <section className="space-y-4">
                <div className="rounded-2xl border border-line bg-panel p-4">
                  <div className="flex items-center justify-between">
                    <h2 className="text-sm font-semibold">语音课堂</h2>
                    <span className="text-[11px] text-muted">{listeningBadge}</span>
                  </div>
                  <p className="mt-2 text-xs text-muted leading-5">{voiceStatus}</p>
                  <button
                    type="button"
                    onMouseDown={() => void startRecording()}
                    onMouseUp={stopRecording}
                    onMouseLeave={stopRecording}
                    onTouchStart={(e) => {
                      e.preventDefault();
                      void startRecording();
                    }}
                    onTouchEnd={(e) => {
                      e.preventDefault();
                      stopRecording();
                    }}
                    className={`mt-4 w-full rounded-xl py-3 text-sm font-medium flex items-center justify-center gap-2 transition ${
                      recording
                        ? 'bg-red-600 hover:bg-red-500'
                        : 'bg-violet-600 hover:bg-violet-500'
                    }`}
                  >
                    <MicIcon />
                    {recording ? '松开结束' : '按住说话'}
                  </button>
                </div>

                <div className="rounded-2xl border border-line bg-panel p-4">
                  <h2 className="text-sm font-semibold mb-3">对话记录</h2>
                  <div className="space-y-2 max-h-[280px] overflow-auto pr-1">
                    {history.length === 0 && <p className="text-xs text-muted">还没有对话</p>}
                    {history.map((item, index) => (
                      <div
                        key={`${item.role}-${index}-${item.text.slice(0, 12)}`}
                        className={`rounded-xl border px-3 py-2 ${
                          item.role === 'user'
                            ? 'border-blue-500/20 bg-blue-500/10'
                            : 'border-line bg-black/20'
                        }`}
                      >
                        <div className="text-[11px] text-muted mb-1">{item.role === 'user' ? '你' : 'AI 老师'}</div>
                        <p className="text-xs leading-5 whitespace-pre-wrap">{item.text}</p>
                      </div>
                    ))}
                  </div>
                </div>

                {view === 'history' && (
                  <div className="rounded-2xl border border-line bg-panel p-4">
                    <div className="flex items-center justify-between mb-3">
                      <h2 className="text-sm font-semibold">本地保存</h2>
                      <span className="text-[11px] text-muted">{saved.length} 条</span>
                    </div>
                    <div className="space-y-2 max-h-[320px] overflow-auto pr-1">
                      {saved.length === 0 && <p className="text-xs text-muted">还没有保存记录</p>}
                      {saved.map((item) => (
                        <button
                          key={item.id}
                          type="button"
                          onClick={() => {
                            setProblem(item.problem);
                            setConfirmed(true);
                            setQuestionState('已从本地记录恢复');
                            setView('workspace');
                            toast('题面已恢复，可继续提问');
                          }}
                          className="w-full text-left rounded-xl border border-line bg-black/20 hover:border-blue-500 px-3 py-3 transition"
                        >
                          <div className="text-sm line-clamp-2">{item.problem}</div>
                          <div className="mt-1 text-[11px] text-muted">
                            {new Date(item.saved_at).toLocaleString()}
                          </div>
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </section>
            </div>
          )}

          {view === 'admin' && isAdmin && (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">用户与系统状态</h2>
                  <p className="text-xs text-muted mt-1">仅管理员可见 · 可调整角色与账号状态</p>
                </div>
                <button
                  type="button"
                  onClick={() => void loadAdmin()}
                  className="inline-flex items-center gap-2 rounded-xl border border-line bg-white/5 hover:bg-white/10 px-3 py-2 text-sm"
                >
                  <RefreshIcon />
                  刷新
                </button>
              </div>

              <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-3">
                {[
                  ['用户总数', adminStats?.users_total ?? '—'],
                  ['活跃用户', adminStats?.users_active ?? '—'],
                  ['管理员', adminStats?.users_by_role?.admin ?? 0],
                  ['教师', adminStats?.users_by_role?.teacher ?? 0],
                  ['学生', adminStats?.users_by_role?.student ?? 0],
                  ['会话', adminStats?.sessions_total ?? '—'],
                  ['推理模式', adminStats?.mode || mode],
                  ['上游', adminStats?.upstream_configured ? '已配置' : '未配置'],
                ].map(([label, value]) => (
                  <div key={String(label)} className="rounded-2xl border border-line bg-panel p-4">
                    <div className="text-[11px] text-muted">{label}</div>
                    <div className="mt-2 text-xl font-semibold">{value}</div>
                  </div>
                ))}
              </div>

              <div className="rounded-2xl border border-line bg-panel p-4">
                <div className="flex flex-wrap gap-2 mb-4">
                  <input
                    value={adminQuery}
                    onChange={(e) => setAdminQuery(e.target.value)}
                    placeholder="搜索邮箱 / 昵称"
                    className="rounded-xl border border-line bg-black/30 px-3 py-2 text-sm outline-none focus:border-blue-500 min-w-[180px]"
                  />
                  <select
                    value={adminRole}
                    onChange={(e) => setAdminRole(e.target.value)}
                    className="rounded-xl border border-line bg-black/30 px-3 py-2 text-sm outline-none"
                  >
                    <option value="">全部角色</option>
                    <option value="admin">管理员</option>
                    <option value="teacher">教师</option>
                    <option value="student">学生</option>
                  </select>
                  <select
                    value={adminStatus}
                    onChange={(e) => setAdminStatus(e.target.value)}
                    className="rounded-xl border border-line bg-black/30 px-3 py-2 text-sm outline-none"
                  >
                    <option value="">全部状态</option>
                    <option value="active">active</option>
                    <option value="disabled">disabled</option>
                  </select>
                  <button
                    type="button"
                    onClick={() => void loadAdmin()}
                    className="rounded-xl bg-blue-600 hover:bg-blue-500 px-4 py-2 text-sm"
                  >
                    查询
                  </button>
                </div>

                <div className="overflow-auto">
                  <table className="min-w-full text-sm">
                    <thead className="text-left text-xs text-muted border-b border-line">
                      <tr>
                        <th className="py-2 pr-3 font-medium">昵称</th>
                        <th className="py-2 pr-3 font-medium">邮箱</th>
                        <th className="py-2 pr-3 font-medium">角色</th>
                        <th className="py-2 pr-3 font-medium">状态</th>
                        <th className="py-2 pr-3 font-medium">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      {adminUsers.map((item) => (
                        <AdminUserRow key={item.id} user={item} onSave={handleAdminSave} />
                      ))}
                      {!adminUsers.length && (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-muted text-sm">
                            {adminLoading ? '加载中…' : '没有匹配的用户'}
                          </td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function AdminUserRow({
  user,
  onSave,
}: {
  user: AdminUser;
  onSave: (userId: string, role: UserRole, status: UserStatus) => Promise<void>;
}) {
  const [role, setRole] = useState<UserRole>(user.role);
  const [status, setStatus] = useState<UserStatus>(user.status);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setRole(user.role);
    setStatus(user.status);
  }, [user.id, user.role, user.status]);

  return (
    <tr className="border-b border-line/70">
      <td className="py-3 pr-3">{user.nickname}</td>
      <td className="py-3 pr-3 text-muted">{user.email}</td>
      <td className="py-3 pr-3">
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-[11px] border ${
            user.role === 'admin'
              ? 'border-amber-500/40 text-amber-300'
              : user.role === 'teacher'
                ? 'border-violet-500/40 text-violet-300'
                : 'border-blue-500/40 text-blue-300'
          }`}
        >
          {roleLabel(user.role)}
        </span>
      </td>
      <td className="py-3 pr-3">
        <span
          className={`inline-flex rounded-full px-2 py-0.5 text-[11px] border ${
            user.status === 'active'
              ? 'border-green-500/40 text-green-300'
              : 'border-red-500/40 text-red-300'
          }`}
        >
          {user.status}
        </span>
      </td>
      <td className="py-3 pr-3">
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as UserRole)}
            className="rounded-lg border border-line bg-black/30 px-2 py-1 text-xs"
          >
            <option value="student">学生</option>
            <option value="teacher">教师</option>
            <option value="admin">管理员</option>
          </select>
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as UserStatus)}
            className="rounded-lg border border-line bg-black/30 px-2 py-1 text-xs"
          >
            <option value="active">active</option>
            <option value="disabled">disabled</option>
          </select>
          <button
            type="button"
            disabled={saving}
            onClick={async () => {
              setSaving(true);
              try {
                await onSave(user.id, role, status);
              } finally {
                setSaving(false);
              }
            }}
            className="rounded-lg bg-white/10 hover:bg-white/15 px-2.5 py-1 text-xs disabled:opacity-60"
          >
            {saving ? '保存中' : '保存'}
          </button>
        </div>
      </td>
    </tr>
  );
}
