const TOKEN_KEY = 'math_coach_token';
const PROGRESS_KEY = 'mathCoachProgress';
const SAVED_KEY = 'mathCoachSaved';

const DEMO_ACCOUNTS = {
  admin: { email: 'teacher@demo.local', password: 'demo123', label: '管理员' },
  teacher: { email: 'math.teacher@demo.local', password: 'demo123', label: '教师' },
  student: { email: 'student@demo.local', password: 'demo123', label: '学生' },
};

const state = {
  user: null,
  view: 'workspace',
  authMode: 'login',
  problem: '',
  sessionId: null,
  confirmed: false,
  stage: 'confirm',
  history: [],
  lastLesson: null,
  annotations: [],
  recorder: null,
  stream: null,
  recording: false,
  progress: Number(localStorage.getItem(PROGRESS_KEY) || 0),
  config: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function toast(message) {
  const el = $('#toast');
  el.textContent = message;
  el.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => el.classList.remove('show'), 2400);
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;');
}

function formatText(value) {
  return escapeHtml(value).replaceAll('\n', '<br>');
}

function getToken() {
  return localStorage.getItem(TOKEN_KEY) || '';
}

function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

function roleLabel(role) {
  return ({ admin: '管理员', teacher: '教师', student: '学生' })[role] || role || '—';
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(path, { ...options, headers });
  if (response.status === 401) {
    setToken('');
    state.user = null;
    showAuth();
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = await response.json();
      detail = payload.detail || payload.error || detail;
      if (Array.isArray(detail)) detail = detail.map((item) => item.msg || JSON.stringify(item)).join('; ');
    } catch (_) {
      // ignore parse errors
    }
    throw new Error(detail || '请求失败');
  }
  if (response.status === 204) return null;
  const contentType = response.headers.get('content-type') || '';
  if (contentType.includes('application/json')) return response.json();
  return response;
}

function showAuth() {
  $('#authScreen').classList.remove('hidden');
  $('#appShell').classList.add('hidden');
}

function showApp() {
  $('#authScreen').classList.add('hidden');
  $('#appShell').classList.remove('hidden');
  renderUser();
  setView(state.view || 'workspace');
}

function renderUser() {
  const user = state.user;
  const nickname = user?.nickname || '未登录';
  $('#userNickname').textContent = nickname;
  $('#userRoleLabel').textContent = roleLabel(user?.role);
  $('#userAvatar').textContent = (nickname || '?').slice(0, 1).toUpperCase();
  const isAdmin = user?.role === 'admin';
  $('#adminNavButton').classList.toggle('hidden', !isAdmin);
  if (!isAdmin && state.view === 'admin') setView('workspace');
}

function setAuthMode(mode) {
  state.authMode = mode;
  $$('.auth-tab').forEach((btn) => btn.classList.toggle('active', btn.dataset.authMode === mode));
  const register = mode === 'register';
  $('#authHint').textContent = register
    ? '公开注册仅支持学生或教师。管理员不可公开注册。'
    : '支持管理员 / 教师 / 学生登录。管理员由系统初始化，不可公开注册。';
  $('#authNicknameLabel').classList.toggle('hidden', !register);
  $('#authNickname').classList.toggle('hidden', !register);
  $('#registerExtra').classList.toggle('hidden', !register);
  $('#demoIdentities').classList.toggle('hidden', register);
  $('#authSubmit').textContent = register ? '注册并登录' : '登录';
  $('#authNickname').required = register;
  syncRegisterFields();
}

function syncRegisterFields() {
  const student = $('#authRole').value === 'student';
  $('#authGradeLabel').classList.toggle('hidden', !student);
  $('#authGrade').classList.toggle('hidden', !student);
}

function applyDemo(id) {
  const account = DEMO_ACCOUNTS[id];
  if (!account) return;
  $('#authEmail').value = account.email;
  $('#authPassword').value = account.password;
  toast(`已填充${account.label}演示账号`);
}

async function bootstrapAuth() {
  try {
    state.config = await api('/api/config');
    if (state.config?.demo_accounts?.length) {
      state.config.demo_accounts.forEach((item) => {
        if (DEMO_ACCOUNTS[item.id]) DEMO_ACCOUNTS[item.id].email = item.email;
      });
    }
  } catch (_) {
    // public config may still work without token
  }

  if (!getToken()) {
    showAuth();
    setAuthMode('login');
    applyDemo('admin');
    return;
  }
  try {
    const me = await api('/api/auth/me');
    state.user = me.user;
    showApp();
    await initWorkspace();
  } catch (_) {
    setToken('');
    showAuth();
    setAuthMode('login');
    applyDemo('admin');
  }
}

async function handleAuthSubmit(event) {
  event.preventDefault();
  $('#authError').classList.add('hidden');
  const email = $('#authEmail').value.trim();
  const password = $('#authPassword').value;
  try {
    let payload;
    if (state.authMode === 'login') {
      payload = await api('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      });
    } else {
      payload = await api('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({
          email,
          password,
          nickname: $('#authNickname').value.trim(),
          role: $('#authRole').value,
          grade: $('#authRole').value === 'student' ? $('#authGrade').value : null,
        }),
      });
    }
    setToken(payload.token);
    state.user = payload.user;
    showApp();
    await initWorkspace();
    toast(`欢迎，${payload.user.nickname}`);
  } catch (error) {
    $('#authError').textContent = error.message || '登录失败';
    $('#authError').classList.remove('hidden');
  }
}

async function logout() {
  try {
    await api('/api/auth/logout', { method: 'POST' });
  } catch (_) {
    // ignore
  }
  setToken('');
  state.user = null;
  state.sessionId = null;
  showAuth();
  setAuthMode('login');
  toast('已退出登录');
}

function setView(view) {
  state.view = view;
  $$('.nav-item').forEach((btn) => btn.classList.toggle('active', btn.dataset.view === view));
  const workspace = view === 'workspace' || view === 'history';
  $('#workspaceView').classList.toggle('hidden', !workspace);
  $('#adminView').classList.toggle('hidden', view !== 'admin');
  $('#saveButton').classList.toggle('hidden', view === 'admin');
  $('#resetButton').classList.toggle('hidden', view === 'admin');
  if (view === 'admin') {
    $('#pageTitle').textContent = '管理后台';
    loadAdmin();
  } else {
    $('#pageTitle').textContent = '今天，从一道题开始。';
    if (view === 'history') openSavedPanel();
  }
}

function updateModeBadge(mode) {
  const badge = $('#modeBadge');
  const upstream = mode === 'minicpm';
  badge.classList.toggle('upstream', upstream);
  badge.classList.toggle('ready', !upstream);
  badge.innerHTML = `<span class="status-dot"></span>${upstream ? 'MiniCPM-o 已连接' : 'Mock 演示模式'}`;
}

function updateProgress() {
  const count = Math.min(state.progress, 3);
  $('#progressCount').textContent = `${count} / 3`;
  $('#progressBar').style.width = `${(count / 3) * 100}%`;
}

function setStage(stage) {
  state.stage = stage;
  const map = { confirm: 0, hint: 1, explain: 2 };
  $$('.stepper-item').forEach((item, index) => {
    item.classList.toggle('active', index === map[stage]);
    item.classList.toggle('done', index < map[stage]);
  });
}

function renderSteps(lesson) {
  const content = $('#lessonContent');
  const steps = (lesson.steps || []).map((step, index) => `
    <div class="lesson-step ${step.state === 'locked' ? 'locked' : ''}">
      <span class="lesson-step-number">${index + 1}</span>
      <div><strong>${escapeHtml(step.title)}</strong><p>${escapeHtml(step.body)}</p></div>
    </div>`).join('');
  const answer = lesson.final_answer
    ? `<div class="answer-box"><span>完整解析 · 最终答案</span><strong>${escapeHtml(lesson.final_answer)}</strong></div>`
    : '';
  content.innerHTML = `
    <div class="reply-meta">AI 老师 · ${lesson.source === 'minicpm' ? 'MiniCPM-o 4.5' : 'Mock 演示'}</div>
    <div class="reply-block"><p>${formatText(lesson.reply)}</p></div>
    <div class="lesson-steps">${steps}</div>
    ${answer}
    <p class="next-question"><strong>下一步：</strong>${escapeHtml(lesson.next_question || '你想继续吗？')}</p>
    ${!lesson.final_answer ? '<button class="button secondary full" id="explainButton" type="button">查看完整解析</button>' : ''}`;
  $('#confidenceBadge').textContent = `置信度 ${Math.round((lesson.confidence || 0) * 100)}%`;
  $('#explainButton')?.addEventListener('click', () => sendLesson('请给出完整、可核验的分步解析。', 'explain'));
  if (lesson.audio_base64) playAudio(lesson.audio_base64, lesson.audio_mime);
}

function renderStreamingReply(text, source = 'mock') {
  $('#lessonContent').innerHTML = `
    <div class="reply-meta">AI 老师 · ${source === 'minicpm' ? 'MiniCPM-o 4.5' : 'Mock 演示'}</div>
    <div class="reply-block streaming-reply" aria-live="polite"><p>${formatText(text)}<span class="stream-cursor" aria-hidden="true"></span></p></div>
    <p class="streaming-status">正在生成分步讲解…</p>`;
}

async function consumeSse(response, onEvent) {
  if (!response.body) throw new Error('浏览器不支持流式响应');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      const line = chunk.split('\n').find((item) => item.startsWith('data: '));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(6)));
    }
  }
}

function appendHistory(role, text) {
  state.history.push({ role, text });
  const list = $('#chatHistory');
  const item = document.createElement('div');
  item.className = `history-item ${role}`;
  item.innerHTML = `<strong>${role === 'user' ? '你' : 'AI 老师'}</strong><p>${escapeHtml(text)}</p>`;
  list.prepend(item);
}

function playAudio(base64, mime = 'audio/wav') {
  const player = $('#ttsPlayer');
  player.src = `data:${mime};base64,${base64}`;
  player.play().catch(() => {});
}

function drawAnnotations(annotations = []) {
  const img = $('#imagePreview');
  const canvas = $('#annotationCanvas');
  const status = $('#annotationStatus');
  if (!img.src || !annotations.length) {
    canvas.classList.add('hidden');
    status.classList.add('hidden');
    return;
  }
  const width = img.clientWidth;
  const height = img.clientHeight;
  canvas.width = width;
  canvas.height = height;
  canvas.classList.remove('hidden');
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 2;
  annotations.forEach((box) => {
    ctx.strokeRect(box.x * width, box.y * height, box.width * width, box.height * height);
  });
  status.textContent = `已标注 ${annotations.length} 个区域`;
  status.classList.remove('hidden');
}

async function loadExamples() {
  const examples = await api('/api/examples');
  const list = $('#exampleList');
  list.innerHTML = examples.map((item) => `
    <button class="example-card" type="button" data-id="${escapeHtml(item.id)}">
      <strong>${escapeHtml(item.title)}</strong>
      <span>${escapeHtml(item.problem)}</span>
    </button>`).join('');
  list.querySelectorAll('.example-card').forEach((button) => {
    button.addEventListener('click', () => {
      const item = examples.find((entry) => entry.id === button.dataset.id);
      if (!item) return;
      $('#problemText').value = item.problem;
      state.problem = item.problem;
      state.annotations = [];
      $('#questionState').textContent = '示例题已填入';
      toast('已填入示例题，请确认题面');
    });
  });
}

async function initWorkspace() {
  updateProgress();
  setStage('confirm');
  try {
    const config = await api('/api/config');
    state.config = config;
    updateModeBadge(config.mode);
  } catch (_) {
    updateModeBadge('mock');
  }
  await loadExamples();
}

async function recognizeImage(file) {
  const body = new FormData();
  body.append('file', file);
  body.append('problem_text', $('#problemText').value || '');
  const result = await api('/api/recognize', { method: 'POST', body });
  state.problem = result.problem || '';
  state.annotations = result.annotations || [];
  $('#problemText').value = state.problem;
  $('#questionState').textContent = result.needs_confirmation ? '请确认题面' : '题面就绪';
  drawAnnotations(state.annotations);
  toast('识别完成，请确认或修改题面');
}

async function confirmProblem() {
  const problem = $('#problemText').value.trim();
  if (!problem) return toast('请先输入或识别题面');
  state.problem = problem;
  state.confirmed = true;
  state.sessionId = null;
  state.history = [];
  $('#chatHistory').innerHTML = '';
  $('#questionState').textContent = '题面已确认';
  setStage('hint');
  await sendLesson('请给我一个提示，不要直接给最终答案。', 'hint');
}

async function sendLesson(message, stage = state.stage || 'hint', audioBase64 = null, sampleRate = 16000) {
  if (!state.problem) return toast('请先确认题面');
  if (!message && !audioBase64) return;
  if (message) appendHistory('user', message);
  setStage(stage);
  renderStreamingReply('', state.config?.mode || 'mock');
  let streamed = '';
  try {
    const response = await api('/api/lesson/stream', {
      method: 'POST',
      body: JSON.stringify({
        session_id: state.sessionId,
        problem: state.problem,
        message: message || '请根据我的语音继续讲解',
        stage,
        tts: true,
        audio_base64: audioBase64,
        audio_sample_rate: sampleRate,
      }),
    });
    let lesson = null;
    await consumeSse(response, (event) => {
      if (event.type === 'session') state.sessionId = event.session_id;
      if (event.type === 'text_delta' && event.text_delta) {
        streamed += event.text_delta;
        renderStreamingReply(streamed, state.config?.mode || 'mock');
      }
      if (event.type === 'lesson') lesson = event.lesson;
    });
    if (!lesson) throw new Error('未收到完整讲解结果');
    state.sessionId = lesson.session_id;
    state.lastLesson = lesson;
    appendHistory('assistant', lesson.reply);
    renderSteps(lesson);
    if (stage === 'explain' && lesson.final_answer) {
      state.progress = Math.min(3, state.progress + 1);
      localStorage.setItem(PROGRESS_KEY, String(state.progress));
      updateProgress();
    }
  } catch (error) {
    toast(error.message || '讲解失败');
  }
}

function saveCurrent() {
  if (!state.problem || !state.lastLesson) return toast('还没有可保存的讲解');
  const saved = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
  saved.unshift({
    id: crypto.randomUUID(),
    problem: state.problem,
    reply: state.lastLesson.reply,
    final_answer: state.lastLesson.final_answer,
    saved_at: new Date().toISOString(),
  });
  localStorage.setItem(SAVED_KEY, JSON.stringify(saved.slice(0, 30)));
  toast('已保存到浏览器本地');
}

function openSavedPanel() {
  const panel = $('#savedPanel');
  const saved = JSON.parse(localStorage.getItem(SAVED_KEY) || '[]');
  $('#savedList').innerHTML = saved.length
    ? saved.map((item) => `
      <button class="saved-item" type="button" data-id="${item.id}">
        <strong>${escapeHtml(item.problem)}</strong>
        <span>${new Date(item.saved_at).toLocaleString()}</span>
      </button>`).join('')
    : '<p class="muted">还没有保存记录</p>';
  panel.classList.remove('hidden');
  $('#savedList').querySelectorAll('.saved-item').forEach((button) => {
    button.addEventListener('click', () => {
      const item = saved.find((entry) => entry.id === button.dataset.id);
      if (!item) return;
      $('#problemText').value = item.problem;
      state.problem = item.problem;
      state.confirmed = true;
      $('#questionState').textContent = '已从本地记录恢复';
      toast('题面已恢复，可继续提问');
      setView('workspace');
      panel.classList.add('hidden');
    });
  });
}

async function resetAll() {
  if (state.sessionId) {
    try { await api(`/api/session/${state.sessionId}`, { method: 'DELETE' }); } catch (_) {}
  }
  state.sessionId = null;
  state.problem = '';
  state.confirmed = false;
  state.history = [];
  state.lastLesson = null;
  state.annotations = [];
  $('#problemText').value = '';
  $('#chatHistory').innerHTML = '';
  $('#imagePreview').removeAttribute('src');
  $('#imagePreviewWrap').classList.add('hidden');
  $('#annotationCanvas').classList.add('hidden');
  $('#annotationStatus').classList.add('hidden');
  $('#questionState').textContent = '等待题目';
  setStage('confirm');
  $('#lessonContent').innerHTML = `
    <div class="empty-lesson">
      <div class="empty-orb">?</div>
      <h3>先确认题面</h3>
      <p>我会先给提示，再按你的节奏展开步骤。</p>
    </div>`;
  toast('已重新开始');
}

async function loadAdmin() {
  if (state.user?.role !== 'admin') return;
  try {
    const stats = await api('/api/admin/stats');
    $('#adminStats').innerHTML = `
      <div class="stat-card"><span>用户总数</span><strong>${stats.users_total}</strong></div>
      <div class="stat-card"><span>活跃用户</span><strong>${stats.users_active}</strong></div>
      <div class="stat-card"><span>管理员</span><strong>${stats.users_by_role?.admin || 0}</strong></div>
      <div class="stat-card"><span>教师</span><strong>${stats.users_by_role?.teacher || 0}</strong></div>
      <div class="stat-card"><span>学生</span><strong>${stats.users_by_role?.student || 0}</strong></div>
      <div class="stat-card"><span>会话</span><strong>${stats.sessions_total}</strong></div>
      <div class="stat-card"><span>推理模式</span><strong>${stats.mode}</strong></div>`;
    const params = new URLSearchParams();
    if ($('#adminRoleFilter').value) params.set('role', $('#adminRoleFilter').value);
    if ($('#adminStatusFilter').value) params.set('status', $('#adminStatusFilter').value);
    if ($('#adminUserQuery').value.trim()) params.set('q', $('#adminUserQuery').value.trim());
    const users = await api(`/api/admin/users?${params.toString()}`);
    const tbody = $('#adminUsersTable tbody');
    tbody.innerHTML = users.map((user) => `
      <tr data-id="${escapeHtml(user.id)}">
        <td>${escapeHtml(user.nickname)}</td>
        <td>${escapeHtml(user.email)}</td>
        <td><span class="role-pill ${escapeHtml(user.role)}">${escapeHtml(roleLabel(user.role))}</span></td>
        <td><span class="status-pill ${escapeHtml(user.status)}">${escapeHtml(user.status)}</span></td>
        <td>
          <div class="admin-actions">
            <select data-field="role">
              <option value="student" ${user.role === 'student' ? 'selected' : ''}>学生</option>
              <option value="teacher" ${user.role === 'teacher' ? 'selected' : ''}>教师</option>
              <option value="admin" ${user.role === 'admin' ? 'selected' : ''}>管理员</option>
            </select>
            <select data-field="status">
              <option value="active" ${user.status === 'active' ? 'selected' : ''}>active</option>
              <option value="disabled" ${user.status === 'disabled' ? 'selected' : ''}>disabled</option>
            </select>
            <button class="button secondary compact" data-action="save" type="button">保存</button>
          </div>
        </td>
      </tr>`).join('');
    tbody.querySelectorAll('button[data-action="save"]').forEach((button) => {
      button.addEventListener('click', async () => {
        const row = button.closest('tr');
        const id = row.dataset.id;
        const role = row.querySelector('select[data-field="role"]').value;
        const statusValue = row.querySelector('select[data-field="status"]').value;
        try {
          await api(`/api/admin/users/${id}`, {
            method: 'PATCH',
            body: JSON.stringify({ role, status: statusValue }),
          });
          toast('用户已更新');
          await loadAdmin();
        } catch (error) {
          toast(error.message || '更新失败');
        }
      });
    });
  } catch (error) {
    toast(error.message || '加载管理后台失败');
  }
}

function bindWorkspaceEvents() {
  $$('.source-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      $$('.source-tab').forEach((item) => item.classList.toggle('active', item === tab));
      $('#uploadView').classList.toggle('hidden', tab.dataset.source !== 'upload');
      $('#examplesView').classList.toggle('hidden', tab.dataset.source !== 'examples');
    });
  });

  $('#imageInput').addEventListener('change', async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    $('#imagePreview').src = url;
    $('#imagePreviewWrap').classList.remove('hidden');
    $('#imagePreview').onload = () => drawAnnotations(state.annotations);
    try {
      await recognizeImage(file);
    } catch (error) {
      toast(error.message || '识别失败');
    }
  });

  $('#removeImage').addEventListener('click', () => {
    $('#imageInput').value = '';
    $('#imagePreview').removeAttribute('src');
    $('#imagePreviewWrap').classList.add('hidden');
    state.annotations = [];
  });

  $('#confirmProblem').addEventListener('click', () => confirmProblem().catch((error) => toast(error.message)));
  $('#sendButton').addEventListener('click', () => {
    const message = $('#messageInput').value.trim();
    $('#messageInput').value = '';
    sendLesson(message, state.confirmed ? state.stage || 'hint' : 'hint');
  });
  $('#messageInput').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      $('#sendButton').click();
    }
  });
  $('#saveButton').addEventListener('click', saveCurrent);
  $('#resetButton').addEventListener('click', () => resetAll());
  $('#historyButton').addEventListener('click', () => setView('history'));
  $('#closeSaved')?.addEventListener('click', () => $('#savedPanel').classList.add('hidden'));
  $('#adminNavButton').addEventListener('click', () => setView('admin'));
  $$('.nav-item[data-view="workspace"]').forEach((btn) => btn.addEventListener('click', () => setView('workspace')));
  $('#refreshAdmin')?.addEventListener('click', () => loadAdmin());
  $('#adminSearchButton')?.addEventListener('click', () => loadAdmin());
  $('#logoutButton').addEventListener('click', () => logout());

  // simple hold-to-talk placeholder using MediaRecorder when available
  const mic = $('#micButton');
  mic.addEventListener('mousedown', startRecording);
  mic.addEventListener('mouseup', stopRecording);
  mic.addEventListener('mouseleave', stopRecording);
  mic.addEventListener('touchstart', (event) => { event.preventDefault(); startRecording(); });
  mic.addEventListener('touchend', (event) => { event.preventDefault(); stopRecording(); });
}

async function startRecording() {
  if (state.recording) return;
  if (!navigator.mediaDevices?.getUserMedia) return toast('当前浏览器不支持录音');
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(state.stream);
    const chunks = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = async () => {
      const blob = new Blob(chunks, { type: 'audio/webm' });
      const buffer = await blob.arrayBuffer();
      const bytes = new Uint8Array(buffer);
      let binary = '';
      bytes.forEach((b) => { binary += String.fromCharCode(b); });
      const base64 = btoa(binary);
      $('#listeningBadge').textContent = '待机';
      $('#voiceStatus').textContent = '语音已发送，正在讲解';
      await sendLesson('请根据我的语音继续讲解', state.stage || 'hint', base64, 16000);
    };
    state.recorder = recorder;
    state.recording = true;
    recorder.start();
    $('#listeningBadge').textContent = '聆听中';
    $('#voiceStatus').textContent = '正在听你说…';
  } catch (_) {
    toast('无法打开麦克风');
  }
}

function stopRecording() {
  if (!state.recording || !state.recorder) return;
  state.recording = false;
  state.recorder.stop();
  state.stream?.getTracks?.().forEach((track) => track.stop());
  state.recorder = null;
  state.stream = null;
}

function bindAuthEvents() {
  $$('.auth-tab').forEach((btn) => btn.addEventListener('click', () => setAuthMode(btn.dataset.authMode)));
  $$('[data-demo]').forEach((btn) => btn.addEventListener('click', () => applyDemo(btn.dataset.demo)));
  $('#authRole').addEventListener('change', syncRegisterFields);
  $('#authForm').addEventListener('submit', handleAuthSubmit);
}

bindAuthEvents();
bindWorkspaceEvents();
bootstrapAuth();
