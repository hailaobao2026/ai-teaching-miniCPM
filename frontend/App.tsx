import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import AuthModal from './components/AuthModal';
import NotebookPanel from './components/NotebookPanel';
import {
  AdminIcon,
  CameraIcon,
  HistoryIcon,
  HomeIcon,
  LogoutIcon,
  MicIcon,
  NotebookIcon,
  RefreshIcon,
  SendIcon,
  SpeakerIcon,
  SparklesIcon,
  StopIcon,
  UploadIcon,
} from './components/Icons';
import { fetchAdminStats, listUsers, updateUser } from './services/adminService';
import { setUnauthorizedHandler } from './services/api';
import { fetchConfig, fetchMe, logout as logoutRequest } from './services/authService';
import {
  deleteSession,
  fetchExamples,
  recognizeImage,
  synthesizeSpeech,
  streamLesson,
} from './services/lessonService';
import { recommendPractice, saveFeedback } from './services/notebookService';
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
  PracticeItem,
  RecognizedProblem,
  SavedLesson,
  SubjectCode,
  User,
  UserRole,
  UserStatus,
} from './types';
import './styles.css';

const PROGRESS_KEY = 'mathCoachProgress';
const SAVED_KEY = 'mathCoachSaved';
const MAX_RECORDING_SECONDS = 60;
const DEFAULT_SUBJECTS = [
  ['chinese', '语文'], ['math', '数学'], ['english', '英语'], ['physics', '物理'], ['chemistry', '化学'],
  ['politics', '政治'], ['history', '历史'], ['geography', '地理'], ['biology', '生物'],
] as const;

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

function formatChatTimestamp(value: string, now = new Date()) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';

  const time = new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date);
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const messageDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const dayDifference = Math.round((today.getTime() - messageDay.getTime()) / 86_400_000);

  if (dayDifference === 0) return `今天 ${time}`;
  if (dayDifference === 1) return `昨天 ${time}`;
  if (date.getFullYear() === now.getFullYear()) {
    return `${date.getMonth() + 1}月${date.getDate()}日 ${time}`;
  }
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${time}`;
}

function formatFullTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatVoiceDuration(seconds = 0) {
  const totalSeconds = Math.max(1, Math.round(seconds));
  const minutes = Math.floor(totalSeconds / 60);
  return `${minutes}:${String(totalSeconds % 60).padStart(2, '0')}`;
}

async function encodeRecording(buffer: ArrayBuffer, targetSampleRate = 16000) {
  const AudioContextConstructor = window.AudioContext || (window as typeof window & { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const audioContext = new AudioContextConstructor();
  try {
    const decoded = await audioContext.decodeAudioData(buffer.slice(0));
    const channelCount = Math.min(2, decoded.numberOfChannels) || 1;
    const channels = Array.from({ length: channelCount }, (_, index) => decoded.getChannelData(index));
    const ratio = decoded.sampleRate / targetSampleRate;
    const outputLength = Math.max(1, Math.round(decoded.length / ratio));
    const output = new Float32Array(outputLength);
    for (let index = 0; index < outputLength; index += 1) {
      const start = index * ratio;
      const end = Math.min(decoded.length, start + ratio);
      let sum = 0;
      let count = 0;
      for (let sample = start; sample < end; sample += 1) {
        for (const channel of channels) sum += channel[Math.floor(sample)] || 0;
        count += channelCount;
      }
      output[index] = count ? sum / count : 0;
    }
    const bytes = new Uint8Array(output.buffer);
    let binary = '';
    const chunkSize = 0x8000;
    for (let index = 0; index < bytes.length; index += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(index, index + chunkSize));
    }
    return { base64: btoa(binary), sampleRate: targetSampleRate };
  } finally {
    await audioContext.close();
  }
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
  imageMime,
  annotations,
}: {
  imageUrl: string | null;
  imageMime: string | null;
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

  if (imageMime === 'application/pdf') {
    return (
      <div className="mt-3 rounded-xl overflow-hidden border border-line bg-black/30">
        <iframe title="题目 PDF 预览" src={imageUrl} className="block w-full h-96 bg-white" />
      </div>
    );
  }

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
  const [subject, setSubject] = useState<SubjectCode>('math');

  const [problem, setProblem] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [stage, setStage] = useState<LessonStage>('confirm');
  const [hasAttempted, setHasAttempted] = useState(false);
  const [history, setHistory] = useState<ChatMessage[]>([]);
  const [lesson, setLesson] = useState<LessonResponse | null>(null);
  const [streamText, setStreamText] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [message, setMessage] = useState('');
  const [sourceTab, setSourceTab] = useState<'text' | 'upload' | 'examples'>('text');
  const [examples, setExamples] = useState<ExampleItem[]>([]);
  const [annotations, setAnnotations] = useState<Annotation[]>([]);
  const [recognizedProblems, setRecognizedProblems] = useState<RecognizedProblem[]>([]);
  const [selectedProblemId, setSelectedProblemId] = useState<string | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imageMime, setImageMime] = useState<string | null>(null);
  const [recognitionWarning, setRecognitionWarning] = useState<string | null>(null);
  const [recognizing, setRecognizing] = useState(false);
  const [cameraActive, setCameraActive] = useState(false);
  const [cameraStarting, setCameraStarting] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [questionState, setQuestionState] = useState('等待题目');
  const [progress, setProgress] = useState(Number(localStorage.getItem(PROGRESS_KEY) || 0));
  const [saved, setSaved] = useState<SavedLesson[]>(() => loadSaved());
  const [recording, setRecording] = useState(false);
  const [voiceStatus, setVoiceStatus] = useState('按住说话');
  const [listeningBadge, setListeningBadge] = useState('待机');
  const [speaking, setSpeaking] = useState(false);
  const [speechLoading, setSpeechLoading] = useState(false);
  const [playingVoiceUrl, setPlayingVoiceUrl] = useState<string | null>(null);
  const [feedbackState, setFeedbackState] = useState<'idle' | 'saving' | 'helpful' | 'wrong'>('idle');
  const [practiceItems, setPracticeItems] = useState<PracticeItem[]>([]);

  const [adminStats, setAdminStats] = useState<AdminStats | null>(null);
  const [adminUsers, setAdminUsers] = useState<AdminUser[]>([]);
  const [adminRole, setAdminRole] = useState('');
  const [adminStatus, setAdminStatus] = useState('');
  const [adminQuery, setAdminQuery] = useState('');
  const [adminLoading, setAdminLoading] = useState(false);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const recordingTimerRef = useRef<number | null>(null);
  const recordingStartedAtRef = useRef<number | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const previewUrlRef = useRef<string | null>(null);
  const cameraStreamRef = useRef<MediaStream | null>(null);
  const cameraVideoRef = useRef<HTMLVideoElement | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const voiceAudioRef = useRef<HTMLAudioElement | null>(null);
  const voiceMessageUrlsRef = useRef<Set<string>>(new Set());
  const speechRequestRef = useRef<AbortController | null>(null);
  const lessonInputRef = useRef<HTMLInputElement | null>(null);
  const historyScrollRef = useRef<HTMLDivElement | null>(null);

  const isAdmin = user?.role === 'admin';
  const mode = config?.mode || 'mock';
  const subjects = config?.subjects?.length ? config.subjects : DEFAULT_SUBJECTS.map(([code, name]) => ({ code: code as SubjectCode, name, icon: name.slice(0, 1), focus: '' }));
  const subjectName = subjects.find((item) => item.code === subject)?.name || '数学';

  const stopAudioPlayback = useCallback(() => {
    speechRequestRef.current?.abort();
    speechRequestRef.current = null;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current = null;
    }
    if (voiceAudioRef.current) {
      voiceAudioRef.current.pause();
      voiceAudioRef.current = null;
    }
    window.speechSynthesis?.cancel();
    setSpeechLoading(false);
    setSpeaking(false);
    setPlayingVoiceUrl(null);
    setVoiceStatus('按住说话');
  }, []);

  const toggleVoicePlayback = useCallback((audioUrl: string) => {
    if (playingVoiceUrl === audioUrl) {
      stopAudioPlayback();
      return;
    }
    stopAudioPlayback();
    const audio = new Audio(audioUrl);
    voiceAudioRef.current = audio;
    audio.onended = () => {
      voiceAudioRef.current = null;
      setPlayingVoiceUrl(null);
    };
    audio.onerror = () => {
      voiceAudioRef.current = null;
      setPlayingVoiceUrl(null);
      toast('语音回放失败');
    };
    setPlayingVoiceUrl(audioUrl);
    audio.play().catch(() => {
      voiceAudioRef.current = null;
      setPlayingVoiceUrl(null);
      toast('无法播放这条语音');
    });
  }, [playingVoiceUrl, stopAudioPlayback]);

  const playLessonAudio = useCallback(
    (base64: string, mime = 'audio/wav') => {
      stopAudioPlayback();
      const audio = new Audio(`data:${mime};base64,${base64}`);
      audioRef.current = audio;
      audio.onended = () => {
        audioRef.current = null;
        setSpeaking(false);
        setVoiceStatus('按住说话');
      };
      audio.onerror = () => {
        audioRef.current = null;
        setSpeaking(false);
        setVoiceStatus('语音播放失败，可查看文字');
      };
      setSpeaking(true);
      setVoiceStatus('AI 老师语音播放中，可随时打断');
      audio.play().catch(() => {
        audioRef.current = null;
        setSpeaking(false);
      });
    },
    [stopAudioPlayback],
  );

  const readLessonAloud = async () => {
    const text = lesson?.reply?.trim();
    if (!text) return;
    if (speechLoading || speaking) {
      stopAudioPlayback();
      return;
    }

    stopAudioPlayback();
    const controller = new AbortController();
    speechRequestRef.current = controller;
    setSpeechLoading(true);
    setVoiceStatus('正在生成朗读语音…');
    try {
      const audio = await synthesizeSpeech(text, subject, controller.signal);
      speechRequestRef.current = null;
      setSpeechLoading(false);
      playLessonAudio(audio.audio_base64, audio.audio_mime || 'audio/wav');
    } catch (error) {
      if (controller.signal.aborted) return;
      speechRequestRef.current = null;
      setSpeechLoading(false);
      if (!('speechSynthesis' in window)) {
        toast(error instanceof Error ? error.message : '语音生成失败');
        setVoiceStatus('语音生成失败，可继续阅读文字');
        return;
      }
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = subject === 'english' ? 'en-US' : 'zh-CN';
      utterance.onend = () => {
        setSpeaking(false);
        setVoiceStatus('按住说话');
      };
      utterance.onerror = () => {
        setSpeaking(false);
        setVoiceStatus('语音播放失败，可继续阅读文字');
      };
      setSpeaking(true);
      setVoiceStatus('浏览器正在朗读，可随时停止');
      window.speechSynthesis.speak(utterance);
    }
  };

  const clearSession = useCallback(() => {
    stopAudioPlayback();
    setUser(null);
    setView('workspace');
  }, [stopAudioPlayback]);

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

      try {
        const me = await fetchMe();
        if (!cancelled) setUser(me);
      } catch {
        // Cookie may be absent, or anonymous mode may be disabled.
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
    if (view === 'notebook') return '错题本与练习推荐';
    return `今天，从一道${subjectName}题开始。`;
  }, [subjectName, view]);

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

  const appendHistory = (
    role: 'user' | 'assistant',
    text: string,
    options: {
      inputType?: ChatMessage['input_type'];
      audioUrl?: string;
      audioDurationSeconds?: number;
    } = {},
  ) => {
    setHistory((prev) => [
      ...prev,
      {
        role,
        text,
        created_at: new Date().toISOString(),
        input_type: options.inputType || 'text',
        audio_url: options.audioUrl,
        audio_duration_seconds: options.audioDurationSeconds,
      },
    ]);
  };

  useEffect(() => {
    const container = historyScrollRef.current;
    if (!container) return;
    window.requestAnimationFrame(() => {
      container.scrollTop = container.scrollHeight;
    });
  }, [history]);

  useEffect(() => {
    const activeUrls = new Set(history.flatMap((item) => item.audio_url ? [item.audio_url] : []));
    voiceMessageUrlsRef.current.forEach((url) => {
      if (activeUrls.has(url)) return;
      if (voiceAudioRef.current?.src === url) {
        voiceAudioRef.current.pause();
        voiceAudioRef.current = null;
        setPlayingVoiceUrl(null);
      }
      URL.revokeObjectURL(url);
      voiceMessageUrlsRef.current.delete(url);
    });
  }, [history]);

  useEffect(() => () => {
    voiceAudioRef.current?.pause();
    voiceMessageUrlsRef.current.forEach((url) => URL.revokeObjectURL(url));
    voiceMessageUrlsRef.current.clear();
  }, []);

  const sendLesson = async (
    userMessage: string,
    nextStage: LessonStage | string,
    audioBase64?: string | null,
    sampleRate = 16000,
    problemOverride?: string,
    appendUserMessage = true,
    countAsAttempt = false,
  ) => {
    const currentProblem = (problemOverride ?? problem).trim();
    if (!currentProblem) {
      toast('请先输入或识别题面');
      return;
    }
    if (streaming) return;

    setStreaming(true);
    stopAudioPlayback();
    setStreamText('');
    setQuestionState(nextStage === 'confirm' ? '确认题面中…' : '讲解生成中…');
    if (userMessage && appendUserMessage) appendHistory('user', userMessage);

    try {
      const streamState: { lesson: LessonResponse | null; source: string } = {
        lesson: null,
        source: mode,
      };

      await streamLesson(
        {
          problem: currentProblem,
          subject,
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
      if (countAsAttempt && latestLesson.stage !== 'explain') setHasAttempted(true);
      setStage(((latestLesson.stage as LessonStage) || (nextStage === 'confirm' ? 'hint' : nextStage) || 'hint') as LessonStage);
      setQuestionState(latestLesson.final_answer ? '完整解析已生成' : '可继续追问');
      appendHistory('assistant', latestLesson.reply);
      if (latestLesson.audio_base64) playLessonAudio(latestLesson.audio_base64, latestLesson.audio_mime || 'audio/wav');
      if ((latestLesson.stage === 'explain' || nextStage === 'explain') && latestLesson.final_answer) {
        updateProgressCount(progress + 1);
      }
      // 单次响应来源不影响全局配置模式：仅在上游降级时提示，不覆盖 config.mode。
      if (latestLesson.source === 'mock' && mode === 'minicpm') {
        toast('MiniCPM-o 暂不可用，本次讲解已切换为演示模式。');
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
    if (recognizing) return toast('题面还在识别中，请稍候');
    const text = problem.trim();
    if (!text) return toast(sourceTab === 'upload' ? '未识别到题面，请手动输入后再确认' : '请先输入题面');
    setProblem(text);
    await sendLesson('题面正确，请带我尝试第一小步。', 'confirm');
  };

  const focusLessonInput = (prefix = '') => {
    setMessage(prefix);
    window.requestAnimationFrame(() => lessonInputRef.current?.focus());
  };

  const stopCamera = useCallback(() => {
    cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
    cameraStreamRef.current = null;
    if (cameraVideoRef.current) cameraVideoRef.current.srcObject = null;
    setCameraActive(false);
    setCameraStarting(false);
  }, []);

  useEffect(() => stopCamera, [stopCamera]);

  const startCamera = async () => {
    if (cameraActive || cameraStarting) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraError('当前浏览器不支持摄像头');
      return;
    }
    setCameraStarting(true);
    setCameraError(null);
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: 'environment' },
          width: { ideal: 1920 },
          height: { ideal: 1440 },
        },
      });
      cameraStreamRef.current = mediaStream;
      if (cameraVideoRef.current) {
        cameraVideoRef.current.srcObject = mediaStream;
        await cameraVideoRef.current.play();
      }
      setCameraActive(true);
    } catch {
      setCameraError('无法打开摄像头，请检查浏览器权限');
      cameraStreamRef.current?.getTracks().forEach((track) => track.stop());
      cameraStreamRef.current = null;
    } finally {
      setCameraStarting(false);
    }
  };

  const captureCameraPhoto = async () => {
    const video = cameraVideoRef.current;
    if (!video || !cameraActive) return;
    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 1280;
    canvas.height = video.videoHeight || 960;
    const context = canvas.getContext('2d');
    if (!context) {
      setCameraError('当前浏览器不支持拍照');
      return;
    }
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.92));
    if (!blob) {
      setCameraError('拍照失败，请重试');
      return;
    }
    const file = new File([blob], `camera-${Date.now()}.jpg`, { type: 'image/jpeg' });
    stopCamera();
    await handleRecognize(file);
  };

  const handleRecognize = async (file: File) => {
    if (file.type === 'application/pdf' && file.size > 8 * 1024 * 1024) {
      toast('PDF 不能超过 8 MB');
      return;
    }
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // Server-side orphaned sessions expire automatically.
      }
    }
    setSessionId(null);
    setProblem('');
    setAnnotations([]);
    setRecognizedProblems([]);
    setSelectedProblemId(null);
    setLesson(null);
    setHistory([]);
    setStreamText('');
    setConfirmed(false);
    setStage('confirm');
    setHasAttempted(false);
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    const url = URL.createObjectURL(file);
    previewUrlRef.current = url;
    setImageUrl(url);
    setImageMime(file.type || 'application/octet-stream');
    setSourceTab('upload');
    setRecognitionWarning(null);
    setRecognizing(true);
    setQuestionState('识题中…');
    try {
      const result = await recognizeImage(file, subject);
      setSessionId(result.session_id || null);
      const items = result.problems?.length
        ? result.problems
        : result.problem
          ? [{ id: result.selected_problem_id || 'problem-1', problem: result.problem, annotations: result.annotations || [] }]
          : [];
      const selected = items.find((item) => item.id === result.selected_problem_id) || items[0];
      setRecognizedProblems(items);
      setSelectedProblemId(selected?.id || null);
      setProblem(selected?.problem || '');
      setAnnotations(selected?.annotations || []);
      setRecognitionWarning(
        result.no_problems
          ? result.message || '这张图片中没有识别到完整题目，请对准一道题重拍，或手动输入题面。'
          : result.degraded
            ? result.degraded_reason || 'MiniCPM-o 识题暂不可用，已降级为演示识题。'
            : null,
      );
      setQuestionState(
        result.no_problems
          ? '未识别到题目'
          : result.degraded
            ? '识题降级，可确认后重试'
            : items.length
              ? `已识别 ${items.length} 题，请选择`
              : '未识别到题面',
      );
      toast(result.no_problems ? '未识别到题目，请重拍或手动输入' : result.degraded ? 'MiniCPM-o 识题失败，已显式降级' : '识题完成');
    } catch (err) {
      setSessionId(null);
      toast(err instanceof Error ? err.message : '识别失败');
      setQuestionState('识题失败');
    } finally {
      setRecognizing(false);
    }
  };

  useEffect(() => () => {
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
  }, []);

  const copyText = async (value: string, ok = '已复制') => {
    try {
      await navigator.clipboard.writeText(value);
      toast(ok);
    } catch {
      toast('复制失败');
    }
  };

  const removeImagePreview = async () => {
    if (!confirmed && sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // Never reuse the ID locally; the server expires orphaned image sessions automatically.
      }
      setSessionId(null);
    }
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setImageUrl(null);
    setImageMime(null);
    setAnnotations([]);
  };

  const loadPractice = async (currentProblem: string) => {
    try {
      const rec = await recommendPractice({ problem: currentProblem, subject, limit: 3 });
      setPracticeItems(rec.items);
    } catch {
      setPracticeItems([]);
    }
  };

  const startProblem = async (nextProblem: string, autoStart = true) => {
    const text = nextProblem.trim();
    if (!text) return;
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // ignore
      }
    }
    setSessionId(null);
    setHistory([]);
    setLesson(null);
    setStreamText('');
    setAnnotations([]);
    setImageUrl(null);
    setMessage('');
    setConfirmed(false);
    setStage('confirm');
    setHasAttempted(false);
    setProblem(text);
    setSourceTab('text');
    setView('workspace');
    setFeedbackState('idle');
    setPracticeItems([]);
    setRecognitionWarning(null);
    setImageMime(null);
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    stopAudioPlayback();
    stopCamera();
    setQuestionState('已载入练习题');
    if (autoStart) {
      await sendLesson('题面正确，请带我尝试第一小步。', 'confirm', null, 16000, text);
    }
  };

  const submitFeedback = async (helpful: boolean) => {
    const currentProblem = problem.trim();
    if (!currentProblem || !lesson) return toast('还没有可反馈的讲解');
    setFeedbackState('saving');
    try {
      await saveFeedback({
        problem: currentProblem,
        helpful,
        note: helpful ? '听懂了' : '没听懂，加入错题本',
        session_id: sessionId,
        stage,
        final_answer: lesson.final_answer || null,
        reply: lesson.reply || null,
        subject,
      });
      setFeedbackState(helpful ? 'helpful' : 'wrong');
      await loadPractice(currentProblem);
      toast(helpful ? '已记录：这题掌握了' : '已加入错题本');
    } catch (err) {
      setFeedbackState('idle');
      toast(err instanceof Error ? err.message : '反馈失败');
    }
  };

  const saveCurrent = () => {
    if (!problem.trim() || !lesson) return toast('还没有可保存的讲解');
    const item: SavedLesson = {
      id: crypto.randomUUID(),
      subject,
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

  const restoreSaved = async (item: SavedLesson) => {
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // Starting a text-only session is still safe after expiry.
      }
    }
    setSessionId(null);
    setSubject(item.subject || 'math');
    setProblem(item.problem);
    setAnnotations([]);
    setRecognizedProblems([]);
    setSelectedProblemId(null);
    setImageUrl(null);
    setImageMime(null);
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    setHistory([]);
    setMessage('');
    setStreamText('');
    setLesson({
      subject: item.subject || 'math',
      reply: item.reply,
      steps: [],
      final_answer: item.final_answer || null,
      next_question: '你可以基于这道题继续追问。',
      confidence: 0.8,
      source: 'mock',
    });
    setConfirmed(true);
    setStage(item.final_answer ? 'explain' : 'hint');
    setHasAttempted(true);
    setQuestionState('已从本地记录恢复');
    setView('workspace');
    toast('题面和解析已恢复，可继续提问');
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
    setHasAttempted(false);
    setHistory([]);
    setLesson(null);
    setStreamText('');
    setAnnotations([]);
    setRecognizedProblems([]);
    setSelectedProblemId(null);
    setImageMime(null);
    setImageUrl(null);
    setMessage('');
    setQuestionState('等待题目');
    setFeedbackState('idle');
    setPracticeItems([]);
    setRecognitionWarning(null);
    if (previewUrlRef.current) URL.revokeObjectURL(previewUrlRef.current);
    previewUrlRef.current = null;
    stopAudioPlayback();
    stopCamera();
    toast('已重新开始');
  };

  const startRecording = async () => {
    if (recording || streaming) return;
    if (!confirmed) {
      toast('请先确认题意，再用语音回答');
      return;
    }
    stopAudioPlayback();
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
        const durationSeconds = Math.max(
          0.1,
          ((performance.now() - (recordingStartedAtRef.current || performance.now())) / 1000),
        );
        const mime = recorder.mimeType || 'audio/webm';
        const blob = new Blob(chunksRef.current, { type: mime });
        chunksRef.current = [];
        recordingStartedAtRef.current = null;
        try {
          if (!blob.size) throw new Error('empty recording');
          const buffer = await blob.arrayBuffer();
          const { base64, sampleRate } = await encodeRecording(buffer);
          const audioUrl = URL.createObjectURL(blob);
          voiceMessageUrlsRef.current.add(audioUrl);
          appendHistory('user', '语音消息', {
            inputType: 'voice',
            audioUrl,
            audioDurationSeconds: durationSeconds,
          });
          setListeningBadge('待机');
          setVoiceStatus('语音已发送，正在讲解');
          await sendLesson(
            '请根据学生语音中的问题或回答继续引导。',
            'hint',
            base64,
            sampleRate,
            undefined,
            false,
            true,
          );
        } catch {
          setListeningBadge('待机');
          setVoiceStatus('录音处理失败，请重试');
          toast('录音处理失败，请重试');
        }
      };
      recorderRef.current = recorder;
      recordingStartedAtRef.current = performance.now();
      recorder.start();
      recordingTimerRef.current = window.setTimeout(() => {
        toast('单次录音最长 60 秒');
        stopRecording();
      }, MAX_RECORDING_SECONDS * 1000);
      setRecording(true);
      setListeningBadge('聆听中');
      setVoiceStatus('正在听你说…');
    } catch {
      toast('无法打开麦克风');
    }
  };

  const stopRecording = () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    setRecording(false);
    if (recordingTimerRef.current) {
      window.clearTimeout(recordingTimerRef.current);
      recordingTimerRef.current = null;
    }
    recorder.stop();
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

  const isSummaryStage = stage === 'explain' || Boolean(lesson?.final_answer);
  const stageIndex = !confirmed ? 0 : isSummaryStage ? 2 : 1;
  const visibleSteps = (lesson?.steps || []).filter((step) => isSummaryStage || step.state !== 'locked');
  const lessonReply = (() => {
    const reply = lesson?.reply.trim() || '';
    if (!isSummaryStage && /[？?]$/.test(reply)) {
      const questionIndex = Math.max(reply.lastIndexOf('？'), reply.lastIndexOf('?'));
      const boundary = Math.max(
        reply.lastIndexOf('。', questionIndex - 1),
        reply.lastIndexOf('！', questionIndex - 1),
        reply.lastIndexOf('\n', questionIndex - 1),
      );
      return boundary >= 0 ? reply.slice(0, boundary + 1).trim() : '';
    }
    return reply;
  })();

  return (
    <div className="min-h-screen bg-canvas text-white flex">
      <aside className="hidden md:flex w-64 shrink-0 border-r border-line bg-[#0c0e16] flex-col p-4 gap-4">
        <div className="flex items-center gap-2 px-1">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-violet-500 flex items-center justify-center text-xs font-bold">
            M
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide">all / coach</div>
            <div className="text-[11px] text-muted">中小学全科智能课堂</div>
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
          <SidebarItem
            active={view === 'notebook'}
            label="错题重练"
            icon={<NotebookIcon active={view === 'notebook'} />}
            onClick={() => setView('notebook')}
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
          <div className="text-[11px] text-muted px-1">MiniCPM-o 4.5 · {subjectName} · turn-based</div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <header className="border-b border-line bg-[#0c0e16]/70 backdrop-blur sticky top-0 z-20">
          <div className="px-4 md:px-6 py-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-[11px] uppercase tracking-[0.18em] text-muted">中小学全科 · 引导式学习</p>
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
                {mode === 'minicpm' ? 'MiniCPM-o Real Mode' : 'Mock Demo Mode'}
              </span>
              {view !== 'admin' && view !== 'notebook' && (
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
            <button type="button" onClick={() => setView('notebook')} className={`px-3 py-1.5 rounded-lg text-xs border ${view === 'notebook' ? 'border-blue-500 text-blue-300' : 'border-line text-muted'}`}>错题重练</button>
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

                <label className="block">
                  <span className="mb-1 block text-[11px] text-muted">当前学科</span>
                  <select
                    value={subject}
                    onChange={(event) => {
                      const next = event.target.value as SubjectCode;
                      if (next === subject) return;
                      stopAudioPlayback();
                      if (sessionId) void deleteSession(sessionId).catch(() => undefined);
                      void removeImagePreview();
                      setSubject(next);
                      setSessionId(null);
                      setProblem('');
                      setLesson(null);
                      setHistory([]);
                      setMessage('');
                      setAnnotations([]);
                      setRecognizedProblems([]);
                      setSelectedProblemId(null);
                      setConfirmed(false);
                      setStage('confirm');
                      setPracticeItems([]);
                      setQuestionState('等待题目');
                    }}
                    className="w-full rounded-xl border border-line bg-black/30 px-3 py-2 text-sm outline-none focus:border-blue-500"
                  >
                    {subjects.map((item) => <option key={item.code} value={item.code}>{item.name}</option>)}
                  </select>
                </label>

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
                    placeholder={`粘贴或输入${subjectName}题面…`}
                    className="w-full rounded-xl border border-line bg-black/30 px-3 py-3 text-sm outline-none focus:border-blue-500 resize-y min-h-[160px]"
                  />
                )}

                {sourceTab === 'upload' && (
                  <div>
                    <div className="rounded-xl border border-line bg-black/20 p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="flex items-center gap-2 text-sm">
                          <CameraIcon />
                          实时拍题
                        </div>
                        <span className="text-[11px] text-muted">{cameraActive ? '摄像头已开启' : '支持试卷 / 草稿纸 / 几何图'}</span>
                      </div>
                      <div className="mt-3 overflow-hidden rounded-lg border border-line bg-black/50">
                        <video
                          ref={cameraVideoRef}
                          className={`block w-full aspect-video object-cover ${cameraActive ? '' : 'hidden'}`}
                          autoPlay
                          muted
                          playsInline
                        />
                        {!cameraActive && (
                          <div className="flex aspect-video items-center justify-center text-xs text-muted">
                            {cameraStarting ? '正在打开摄像头…' : '摄像头未开启'}
                          </div>
                        )}
                      </div>
                      <div className="mt-3 grid grid-cols-3 gap-2">
                        <button
                          type="button"
                          disabled={cameraStarting || cameraActive}
                          onClick={() => void startCamera()}
                          className="rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-60 py-2 text-xs"
                        >
                          {cameraStarting ? '开启中…' : '开启摄像头'}
                        </button>
                        <button
                          type="button"
                          disabled={!cameraActive}
                          onClick={() => void captureCameraPhoto()}
                          className="rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-60 py-2 text-xs"
                        >
                          拍摄题目
                        </button>
                        <button
                          type="button"
                          disabled={!cameraActive}
                          onClick={stopCamera}
                          className="rounded-lg border border-line bg-white/5 hover:bg-white/10 disabled:opacity-60 py-2 text-xs"
                        >
                          关闭
                        </button>
                      </div>
                      {cameraError && <p className="mt-2 text-[11px] text-amber-300">{cameraError}</p>}
                    </div>
                    <label className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-black/20 px-4 py-8 cursor-pointer hover:border-blue-500 transition">
                      <UploadIcon />
                      <span className="text-sm">上传题目图片或 PDF</span>
                      <span className="text-[11px] text-muted">支持 PNG / JPEG / WebP / PDF，最大 8 MB</span>
                      <input
                        type="file"
                        accept="image/*,application/pdf"
                        className="hidden"
                        onChange={(e) => {
                          const file = e.target.files?.[0];
                          if (file) void handleRecognize(file);
                        e.target.value = '';
                      }}
                    />
                    </label>
                    {recognitionWarning && (
                      <p className="mt-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] leading-5 text-amber-200">
                        {recognitionWarning}
                      </p>
                    )}
                    {recognizedProblems.length > 0 && (
                      <div className="mt-3 space-y-2">
                        <div className="text-[11px] text-muted">识别到 {recognizedProblems.length} 道题，请选择要学习的一题：</div>
                        <div role="radiogroup" aria-label="识别出的候选题目" className="max-h-52 space-y-2 overflow-auto pr-1">
                          {recognizedProblems.map((item, index) => (
                            <button
                              key={item.id}
                              type="button"
                              role="radio"
                              aria-checked={selectedProblemId === item.id}
                              onClick={() => {
                                setSelectedProblemId(item.id);
                                setProblem(item.problem);
                                setAnnotations(item.annotations || []);
                              }}
                              className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                                selectedProblemId === item.id
                                  ? 'border-blue-500 bg-blue-500/10 text-blue-100'
                                  : 'border-line bg-black/20 text-muted hover:border-blue-500/60'
                              }`}
                            >
                              <span className="flex items-center gap-2 text-[11px] font-medium">
                                <span
                                  className={`w-3.5 h-3.5 rounded-full border ${
                                    selectedProblemId === item.id
                                      ? 'border-blue-400 bg-blue-500'
                                      : 'border-line bg-transparent'
                                  }`}
                                  aria-hidden="true"
                                />
                                题目 {index + 1}
                              </span>
                              <p className="mt-1 line-clamp-2">{item.problem}</p>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <AnnotationCanvas imageUrl={imageUrl} imageMime={imageMime} annotations={annotations} />
                    {imageUrl && (
                      <button
                        type="button"
                        className="mt-2 text-xs text-muted hover:text-white"
                        onClick={() => void removeImagePreview()}
                      >
                        {confirmed ? '隐藏图片预览' : '移除图片和识题上下文'}
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
                    {examples.filter((item) => !item.subject || item.subject === subject).map((item) => (
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
                    {!examples.some((item) => !item.subject || item.subject === subject) && <p className="text-xs text-muted">暂无例题</p>}
                  </div>
                )}

                <button
                  type="button"
                  disabled={streaming || recognizing}
                  onClick={() => void confirmProblem()}
                  className="flex min-h-11 w-full items-center justify-center gap-2 rounded-xl bg-blue-600 px-3 text-sm font-medium transition hover:bg-blue-500 disabled:opacity-60"
                >
                  <SparklesIcon />
                  {recognizing ? '题面识别中…' : '题意正确，开始尝试'}
                </button>
              </section>

              <section className="rounded-2xl border border-line bg-panel p-4 flex flex-col min-h-[560px]">
                <div className="mb-4 flex items-start justify-between gap-3">
                  <div className="grid min-w-0 flex-1 grid-cols-3" aria-label="学习进度">
                    {['看懂题目', '尝试一步', '总结方法'].map((label, index) => (
                      <div key={label} className="relative flex min-w-0 flex-col items-center gap-1 text-center">
                        {index > 0 && (
                          <span className={`absolute right-1/2 top-3 h-px w-full ${index <= stageIndex ? 'bg-blue-500/70' : 'bg-line'}`} />
                        )}
                        <span
                          aria-current={index === stageIndex ? 'step' : undefined}
                          className={`relative z-10 flex h-6 w-6 items-center justify-center rounded-full border text-[11px] ${
                            index < stageIndex
                              ? 'border-green-500/50 bg-green-500/20 text-green-300'
                              : index === stageIndex
                                ? 'border-blue-400 bg-blue-600 text-white'
                                : 'border-line bg-panel text-muted'
                          }`}
                        >
                          {index < stageIndex ? '✓' : index + 1}
                        </span>
                        <span className={`truncate text-[11px] ${index === stageIndex ? 'text-blue-200' : index < stageIndex ? 'text-green-300' : 'text-muted'}`}>
                          {label}
                        </span>
                      </div>
                    ))}
                  </div>
                  {lesson && (
                    <span className="shrink-0 pt-1 text-[11px] text-muted">
                      置信度 {Math.round((lesson.confidence || 0) * 100)}%
                    </span>
                  )}
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
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-[11px] text-muted">
                          AI 老师 · {lesson.source === 'minicpm' ? 'MiniCPM-o 4.5' : 'Mock 演示'}
                        </div>
                        <button
                          type="button"
                          onClick={() => void readLessonAloud()}
                          title={speechLoading ? '取消语音生成' : speaking ? '停止朗读' : '朗读当前讲解'}
                          className="inline-flex min-h-11 min-w-[76px] items-center justify-center gap-1.5 rounded-lg border border-line bg-white/5 px-2.5 text-xs text-gray-200 hover:bg-white/10"
                        >
                          {speechLoading || speaking ? <StopIcon /> : <SpeakerIcon />}
                          {speechLoading ? '取消' : speaking ? '停止' : '朗读'}
                        </button>
                      </div>
                      {lessonReply && <p className="whitespace-pre-wrap text-sm leading-7">{lessonReply}</p>}

                      {visibleSteps.length > 0 && (
                        <div className="space-y-2">
                          {visibleSteps.map((step, index) => (
                          <div
                            key={`${step.title}-${index}`}
                            className="rounded-lg border border-line bg-black/20 px-3 py-3"
                          >
                            <div className="flex gap-3">
                              <div className="w-6 h-6 rounded-full bg-blue-600/20 text-blue-300 text-xs flex items-center justify-center shrink-0">
                                {index + 1}
                              </div>
                              <div className="min-w-0">
                                <div className="text-sm font-medium">{step.title}</div>
                                <p className="mt-1 whitespace-pre-wrap text-xs leading-6 text-muted">{step.body}</p>
                              </div>
                            </div>
                          </div>
                          ))}
                        </div>
                      )}

                      {!isSummaryStage && (
                        <div className="space-y-3 rounded-lg border border-blue-500/40 bg-blue-500/10 p-3">
                          <div>
                            <div className="text-[11px] font-medium text-blue-300">轮到你</div>
                            <p className="mt-1 text-sm font-medium leading-6 text-gray-100">
                              {lesson.next_question || '你愿意先试着回答这个小问题吗？'}
                            </p>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <button
                              type="button"
                              disabled={streaming}
                              onClick={() => void sendLesson('请给我一点提示，只提示当前这一小步，不要公布答案。', 'hint')}
                              className="min-h-11 rounded-lg border border-blue-500/30 bg-blue-500/10 px-2 text-xs text-blue-100 hover:bg-blue-500/20 disabled:opacity-60"
                            >
                              给点提示
                            </button>
                            <button
                              type="button"
                              disabled={streaming}
                              onClick={() => void sendLesson('我没看懂刚才的说法，请用更简单的话换一种方式，只问一个问题。', 'hint')}
                              className="min-h-11 rounded-lg border border-line bg-white/5 px-2 text-xs hover:bg-white/10 disabled:opacity-60"
                            >
                              换种说法
                            </button>
                            <button
                              type="button"
                              disabled={streaming}
                              onClick={() => void sendLesson('我现在不会做。请从最基础的已知条件开始，把问题再拆小一点。', 'hint')}
                              className="min-h-11 rounded-lg border border-line bg-white/5 px-2 text-xs hover:bg-white/10 disabled:opacity-60"
                            >
                              我不会
                            </button>
                            <button
                              type="button"
                              disabled={streaming}
                              onClick={() => focusLessonInput('我的想法是：')}
                              className="min-h-11 rounded-lg bg-blue-600 px-2 text-xs font-medium hover:bg-blue-500 disabled:opacity-60"
                            >
                              我先试试
                            </button>
                          </div>
                          <div className="grid grid-cols-2 gap-2 border-t border-blue-500/20 pt-3">
                            <button
                              type="button"
                              disabled={streaming}
                              onClick={() => void sendLesson('这一步我懂了，请继续下一个小问题。', 'hint')}
                              className="min-h-11 rounded-lg border border-green-500/30 bg-green-500/10 px-2 text-xs text-green-200 hover:bg-green-500/20 disabled:opacity-60"
                            >
                              这一步懂了
                            </button>
                            <button
                              type="button"
                              disabled={streaming}
                              onClick={() => void sendLesson('这一步我还不懂，请把问题再拆小一点，只问我一个更简单的问题。', 'hint')}
                              className="min-h-11 rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 text-xs text-amber-100 hover:bg-amber-500/20 disabled:opacity-60"
                            >
                              这一步不懂
                            </button>
                          </div>
                        </div>
                      )}

                      {isSummaryStage && lesson.final_answer && (
                        <div className="rounded-xl border border-green-500/30 bg-green-500/10 px-3 py-3">
                          <div className="flex items-center justify-between gap-2">
                            <div className="text-[11px] text-green-300">最终答案</div>
                            <button
                              type="button"
                              onClick={() => void copyText(lesson.final_answer || '', '答案已复制')}
                              className="min-h-11 px-2 text-[11px] text-green-200 hover:text-white"
                            >
                              复制
                            </button>
                          </div>
                          <div className="mt-1 text-sm font-semibold">{lesson.final_answer}</div>
                        </div>
                      )}

                      {!isSummaryStage ? (
                        <div className="space-y-2">
                          <button
                            type="button"
                            disabled={!hasAttempted || streaming}
                            onClick={() => void sendLesson('我已经完成一次尝试。请结合我的尝试总结完整解题方法和最终答案。', 'explain')}
                            className="min-h-11 w-full rounded-lg border border-green-500/40 bg-green-500/10 px-3 text-sm font-medium text-green-100 hover:bg-green-500/20 disabled:opacity-60"
                          >
                            总结方法
                          </button>
                          <p className="text-center text-[11px] text-muted">
                            {hasAttempted ? '已记录你的尝试，可以进入方法总结。' : '先发送一次你的想法或语音回答，即可总结方法。'}
                          </p>
                        </div>
                      ) : (
                        <button
                          type="button"
                          disabled={streaming}
                          onClick={() => focusLessonInput('我学到的方法是：')}
                          className="min-h-11 w-full rounded-lg border border-blue-500/40 bg-blue-500/10 px-3 text-sm font-medium text-blue-100 hover:bg-blue-500/20 disabled:opacity-60"
                        >
                          用一句话总结
                        </button>
                      )}

                      {isSummaryStage && (
                        <div className="space-y-3 rounded-lg border border-line bg-black/20 p-3">
                          <div className="text-[11px] text-muted">这道题的掌握情况</div>
                        <div className="grid grid-cols-2 gap-2">
                          <button
                            type="button"
                            disabled={feedbackState === 'saving'}
                            onClick={() => void submitFeedback(true)}
                            className={`min-h-11 rounded-lg border px-2 text-xs ${
                              feedbackState === 'helpful'
                                ? 'border-green-500/40 bg-green-500/15 text-green-300'
                                : 'border-line bg-white/5 hover:bg-white/10'
                            }`}
                          >
                            {feedbackState === 'helpful' ? '已标记掌握' : '这题掌握了'}
                          </button>
                          <button
                            type="button"
                            disabled={feedbackState === 'saving'}
                            onClick={() => void submitFeedback(false)}
                            className={`min-h-11 rounded-lg border px-2 text-xs ${
                              feedbackState === 'wrong'
                                ? 'border-amber-500/40 bg-amber-500/15 text-amber-200'
                                : 'border-line bg-white/5 hover:bg-white/10'
                            }`}
                          >
                            {feedbackState === 'wrong' ? '已加入错题本' : '还需巩固'}
                          </button>
                        </div>
                        {practiceItems.length > 0 && (
                          <div className="space-y-2">
                            <div className="text-[11px] text-muted">同类练习</div>
                            {practiceItems.map((item) => (
                              <button
                                key={item.id}
                                type="button"
                                onClick={() => void startProblem(item.problem)}
                                className="min-h-11 w-full rounded-lg border border-line bg-black/30 px-3 py-2 text-left hover:border-blue-500"
                              >
                                <div className="text-xs">{item.problem}</div>
                                <div className="mt-1 text-[11px] text-blue-300">{item.reason}</div>
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                      )}
                    </div>
                  )}

                  {!streaming && !lesson && (
                    <div className="h-full min-h-[280px] flex flex-col items-center justify-center text-center px-6">
                      <div className="w-14 h-14 rounded-full bg-blue-600/15 border border-blue-500/30 flex items-center justify-center text-xl text-blue-300 mb-3">
                        ?
                      </div>
                      <h3 className="text-base font-medium">先看懂题目</h3>
                      <p className="mt-2 text-sm text-muted">确认题意后，我们一次只解决一个小问题。</p>
                    </div>
                  )}
                </div>

                <div className="mt-4 flex gap-2">
                  <input
                    ref={lessonInputRef}
                    value={message}
                    onChange={(e) => setMessage(e.target.value)}
                    disabled={!confirmed || streaming}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && !e.shiftKey) {
                        e.preventDefault();
                        const text = message.trim();
                        if (!text || streaming) return;
                        setMessage('');
                        if (!confirmed) return;
                        void sendLesson(text, 'hint', undefined, 16000, undefined, true, true);
                      }
                    }}
                    placeholder={confirmed ? (isSummaryStage ? '写下你的方法总结或继续提问' : '写下你的想法或回答') : '先确认题意后再回答'}
                    className="min-h-11 min-w-0 flex-1 rounded-xl border border-line bg-black/30 px-3 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-500/20"
                  />
                  <button
                    type="button"
                    disabled={!confirmed || streaming}
                    onClick={() => {
                      const text = message.trim();
                      if (!text) return;
                      setMessage('');
                      if (!confirmed) return;
                      void sendLesson(text, 'hint', undefined, 16000, undefined, true, true);
                    }}
                    className="flex min-h-11 shrink-0 items-center gap-1 rounded-xl bg-blue-600 px-3 text-sm hover:bg-blue-500 disabled:opacity-60"
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
                    <span className={`text-[11px] ${speaking ? 'text-blue-300' : 'text-muted'}`}>
                      {speaking ? 'AI 语音回答中' : listeningBadge}
                    </span>
                  </div>
                  <p className="mt-2 text-xs text-muted leading-5">{voiceStatus}</p>
                  {(speaking || speechLoading) && (
                    <button
                      type="button"
                      onClick={stopAudioPlayback}
                      className="mt-2 w-full rounded-xl border border-line bg-white/5 hover:bg-white/10 py-2 text-xs"
                    >
                      {speechLoading ? '取消语音生成' : '打断语音回答'}
                    </button>
                  )}
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
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h2 className="text-sm font-semibold">对话记录</h2>
                    <span className="text-[11px] text-muted">{history.length} 条</span>
                  </div>
                  <div ref={historyScrollRef} className="space-y-2 max-h-[280px] overflow-auto pr-1">
                    {history.length === 0 && <p className="text-xs text-muted">还没有对话</p>}
                    {history.map((item, index) => (
                      <div
                        key={`${item.created_at}-${item.role}-${index}`}
                        className={`rounded-xl border px-3 py-2 ${
                          item.role === 'user'
                            ? 'border-blue-500/20 bg-blue-500/10'
                            : 'border-line bg-black/20'
                        }`}
                      >
                        <div className="mb-1 flex items-center justify-between gap-2 text-[11px] text-muted">
                          <span className="flex min-w-0 items-center gap-2">
                            <span>{item.role === 'user' ? '你' : 'AI 老师'}</span>
                            {item.input_type === 'voice' && (
                              <span className="text-blue-300">语音输入</span>
                            )}
                          </span>
                          <time
                            dateTime={item.created_at}
                            title={formatFullTimestamp(item.created_at)}
                            className="shrink-0 whitespace-nowrap text-gray-400"
                          >
                            {formatChatTimestamp(item.created_at)}
                          </time>
                        </div>
                        {item.input_type === 'voice' && item.audio_url ? (
                          <button
                            type="button"
                            aria-label={playingVoiceUrl === item.audio_url ? '停止语音消息' : '播放语音消息'}
                            onClick={() => toggleVoicePlayback(item.audio_url || '')}
                            className="flex min-h-11 w-full items-center justify-between gap-3 rounded-lg border border-blue-500/30 bg-blue-500/10 px-3 text-xs text-blue-100 transition-colors hover:bg-blue-500/20 focus:outline-none focus:ring-2 focus:ring-blue-400/50"
                          >
                            <span className="flex items-center gap-2">
                              {playingVoiceUrl === item.audio_url ? <StopIcon /> : <SpeakerIcon />}
                              {playingVoiceUrl === item.audio_url ? '停止播放' : '播放语音'}
                            </span>
                            <span className="shrink-0 text-blue-200">
                              {formatVoiceDuration(item.audio_duration_seconds)}
                            </span>
                          </button>
                        ) : (
                          <p className="text-xs leading-5 whitespace-pre-wrap">{item.text}</p>
                        )}
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
                          onClick={() => void restoreSaved(item)}
                          className="w-full text-left rounded-xl border border-line bg-black/20 hover:border-blue-500 px-3 py-3 transition"
                        >
                          <div className="text-sm line-clamp-2">{item.problem}</div>
                          <div className="mt-1 text-[11px] text-muted line-clamp-2">{item.reply}</div>
                          {item.final_answer && (
                            <div className="mt-1 text-[11px] text-green-300">最终答案：{item.final_answer}</div>
                          )}
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

          {view === 'notebook' && (
            <NotebookPanel onPractice={(nextProblem) => void startProblem(nextProblem)} />
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
