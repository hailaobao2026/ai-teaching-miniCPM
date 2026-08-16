import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  deleteNotebookItem,
  fetchNotebook,
  markNotebookMastered,
  recommendPractice,
  submitNotebookAttempt,
} from '../services/notebookService';
import type { NotebookAttemptResponse, NotebookItem, NotebookStats, PracticeItem } from '../types';

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

export default function NotebookPanel({
  onPractice,
}: {
  onPractice: (problem: string) => void;
}) {
  const [filter, setFilter] = useState<'all' | 'wrong' | 'mastered'>('wrong');
  const [items, setItems] = useState<NotebookItem[]>([]);
  const [retryItems, setRetryItems] = useState<NotebookItem[]>([]);
  const [stats, setStats] = useState<NotebookStats>({ total: 0, wrong: 0, mastered: 0 });
  const [recommended, setRecommended] = useState<PracticeItem[]>([]);
  const [recommendTopic, setRecommendTopic] = useState('综合练习');
  const [loading, setLoading] = useState(false);
  const [selectedItemByTopic, setSelectedItemByTopic] = useState<Record<string, string>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, NotebookAttemptResponse>>({});
  const [submittingId, setSubmittingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const wrongPayload = await fetchNotebook({ filter: 'wrong', limit: 100 });
      const preferredTopic = wrongPayload.items[0]?.topic;
      const [notebook, practice] = await Promise.all([
        fetchNotebook({ filter, limit: 50 }),
        recommendPractice({ topic: preferredTopic, limit: 4 }),
      ]);
      setRetryItems(wrongPayload.items);
      setItems(notebook.items);
      setStats(notebook.stats);
      setRecommended(practice.items);
      setRecommendTopic(practice.topic_label);
      setSelectedItemByTopic((current) => {
        const next: Record<string, string> = {};
        wrongPayload.items.forEach((item) => {
          next[item.topic] = current[item.topic] === item.id ? item.id : next[item.topic] || item.id;
        });
        return next;
      });
    } catch (err) {
      toast(err instanceof Error ? err.message : '加载错题本失败');
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load();
  }, [load]);

  const groupedRetryItems = useMemo(() => {
    const groups = new Map<string, NotebookItem[]>();
    retryItems.forEach((item) => {
      groups.set(item.topic, [...(groups.get(item.topic) || []), item]);
    });
    return [...groups.entries()]
      .map(([topic, groupItems]) => {
        const selectedItem =
          groupItems.find((item) => item.id === selectedItemByTopic[topic]) || groupItems[0];
        return {
          topic,
          label: selectedItem.topic_label,
          count: groupItems.length,
          item: selectedItem,
        };
      })
      .sort((left, right) => right.count - left.count || left.label.localeCompare(right.label, 'zh-Hans-CN'));
  }, [retryItems, selectedItemByTopic]);

  const masteryRate = stats.total ? Math.round((stats.mastered / stats.total) * 100) : 0;

  const updateAfterAttempt = (payload: NotebookAttemptResponse) => {
    setResults((current) => ({ ...current, [payload.item.id]: payload }));
    setRetryItems((current) =>
      payload.item.helpful
        ? current.filter((item) => item.id !== payload.item.id)
        : current.map((item) => (item.id === payload.item.id ? payload.item : item)),
    );
    setItems((current) =>
      current.map((item) => (item.id === payload.item.id ? payload.item : item)),
    );
  };

  const submitAnswer = async (item: NotebookItem) => {
    const answer = (answers[item.id] || '').trim();
    if (!answer) {
      toast('请先输入你的最终答案');
      return;
    }
    setSubmittingId(item.id);
    try {
      const payload = await submitNotebookAttempt(item.id, answer);
      updateAfterAttempt(payload);
      if (payload.correct) {
        toast('答对了，这题已标记掌握');
        await load();
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : '提交答案失败');
    } finally {
      setSubmittingId(null);
    }
  };

  const markMastered = async (item: NotebookItem) => {
    setSubmittingId(item.id);
    try {
      const payload = await markNotebookMastered(item.id);
      setRetryItems((current) => current.filter((retry) => retry.id !== item.id));
      toast('已记录：看完答案后理解了这题');
      await load();
      if (filter !== 'all' && filter !== 'mastered') {
        setItems((current) => current.filter((listed) => listed.id !== payload.item.id));
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : '标记失败');
    } finally {
      setSubmittingId(null);
    }
  };

  const removeItem = async (item: NotebookItem) => {
    try {
      await deleteNotebookItem(item.id);
      toast('已从错题本移除');
      await load();
    } catch (err) {
      toast(err instanceof Error ? err.message : '删除失败');
    }
  };

  return (
    <div className="space-y-4">
      <section className="rounded-2xl border border-line bg-panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold">待重练优先</h2>
            <p className="mt-1 text-[11px] text-muted">按薄弱知识点聚合；先作答，再看递进提示</p>
          </div>
          <div className="flex items-center gap-3 text-[11px] text-muted">
            <span>待重练 {stats.wrong}</span>
            <span>掌握率 {masteryRate}%</span>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {loading && retryItems.length === 0 && <p className="text-xs text-muted">加载中…</p>}
          {!loading && groupedRetryItems.length === 0 && (
            <p className="py-8 text-center text-xs text-muted">太棒了，当前没有待重练错题。</p>
          )}
          {groupedRetryItems.map((group) => {
            const result = results[group.item.id];
            return (
              <article
                key={group.topic}
                className="rounded-xl border border-blue-500/50 bg-blue-500/5 p-3 transition"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] rounded-full border border-blue-500/30 text-blue-300 px-2 py-0.5">
                      {group.label}
                    </span>
                    <span className="text-[11px] text-muted">{group.count} 题待重练</span>
                  </div>
                  {group.count > 1 && (
                    <button
                      type="button"
                      onClick={() =>
                        setSelectedItemByTopic((current) => ({ ...current, [group.topic]: group.item.id }))
                      }
                      className="text-[11px] text-blue-300 hover:text-blue-200"
                    >
                      从这题开始
                    </button>
                  )}
                </div>

                <p className="mt-2 text-sm leading-6">{group.item.problem}</p>
                <div className="mt-1 text-[11px] text-muted">
                  已重练 {group.item.attempt_count} 次 · 答对 {group.item.correct_count} 次
                  {group.item.consecutive_wrong ? ` · 连错 ${group.item.consecutive_wrong} 次` : ''}
                </div>

                <div className="mt-3 flex flex-col sm:flex-row gap-2">
                  <input
                    value={answers[group.item.id] || ''}
                    onChange={(event) =>
                      setAnswers((current) => ({ ...current, [group.item.id]: event.target.value }))
                    }
                    placeholder="输入最终答案，例如 x=6 或 (1.5, 0)"
                    className="flex-1 rounded-lg border border-line bg-black/30 px-3 py-2 text-sm outline-none focus:border-blue-500"
                  />
                  <button
                    type="button"
                    disabled={submittingId === group.item.id}
                    onClick={() => void submitAnswer(group.item)}
                    className="rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-60 px-4 py-2 text-xs font-medium"
                  >
                    {submittingId === group.item.id ? '判定中…' : '提交答案'}
                  </button>
                </div>

                {result && (
                  <div
                    className={`mt-3 rounded-lg border p-3 text-xs leading-6 ${
                      result.correct
                        ? 'border-green-500/30 bg-green-500/10 text-green-200'
                        : 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                    }`}
                  >
                    <div className="font-medium">{result.hint.title}</div>
                    <p className="mt-1">{result.hint.body}</p>
                    {result.can_mark_mastered && !result.correct && (
                      <button
                        type="button"
                        disabled={submittingId === group.item.id}
                        onClick={() => void markMastered(group.item)}
                        className="mt-3 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-60 px-3 py-1.5 text-xs"
                      >
                        我看懂答案了，标记掌握
                      </button>
                    )}
                  </div>
                )}
              </article>
            );
          })}
        </div>
      </section>

      <div className="grid sm:grid-cols-3 gap-3">
        {[
          ['待重练', stats.wrong, '答对一次自动移出'],
          ['已掌握', stats.mastered, '标记听懂或重练答对'],
          ['全部记录', stats.total, '反馈会同步到账号'],
        ].map(([label, value, hint]) => (
          <div key={String(label)} className="rounded-2xl border border-line bg-panel p-4">
            <div className="text-[11px] text-muted">{label}</div>
            <div className="mt-1 text-2xl font-semibold">{value}</div>
            <div className="mt-1 text-[11px] text-muted">{hint}</div>
          </div>
        ))}
      </div>

      <div className="grid xl:grid-cols-[minmax(0,1fr)_320px] gap-4">
        <section className="rounded-2xl border border-line bg-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h2 className="text-sm font-semibold">错题记录</h2>
              <p className="text-[11px] text-muted mt-1">按账号保存，不写入原图和录音</p>
            </div>
            <div className="flex gap-1 rounded-xl border border-line bg-black/30 p-1">
              {([
                ['wrong', '没听懂'],
                ['mastered', '已掌握'],
                ['all', '全部'],
              ] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setFilter(id)}
                  className={`px-3 py-1.5 rounded-lg text-xs transition ${
                    filter === id ? 'bg-blue-600 text-white' : 'text-muted hover:text-white'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            {loading && <p className="text-xs text-muted">加载中…</p>}
            {!loading && items.length === 0 && (
              <p className="text-xs text-muted py-8 text-center">
                {filter === 'wrong' ? '还没有错题。讲解后点“没听懂”即可收录。' : '还没有记录'}
              </p>
            )}
            {items.map((item) => (
              <div key={item.id} className="rounded-xl border border-line bg-black/20 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px] rounded-full border border-blue-500/30 text-blue-300 px-2 py-0.5">
                    {item.topic_label}
                  </span>
                  <span className={`text-[11px] ${item.helpful ? 'text-green-300' : 'text-amber-200'}`}>
                    {item.helpful ? '已掌握' : `待重练 ${item.attempt_count} 次`}
                  </span>
                </div>
                <p className="mt-2 text-sm leading-6">{item.problem}</p>
                {item.note && <p className="mt-1 text-[11px] text-muted">备注：{item.note}</p>}
                {item.helpful && item.final_answer && (
                  <p className="mt-1 text-[11px] text-muted">参考答案：{item.final_answer}</p>
                )}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => onPractice(item.problem)}
                    className="rounded-lg bg-blue-600 hover:bg-blue-500 px-3 py-1.5 text-xs"
                  >
                    回到讲解
                  </button>
                  <button
                    type="button"
                    onClick={() => void removeItem(item)}
                    className="rounded-lg border border-line bg-white/5 hover:bg-white/10 px-3 py-1.5 text-xs"
                  >
                    移除
                  </button>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-2xl border border-line bg-panel p-4 h-fit">
          <h2 className="text-sm font-semibold">同类练习推荐</h2>
          <p className="mt-1 text-[11px] text-muted">优先补最薄弱知识点 · {recommendTopic}</p>
          <div className="mt-3 space-y-2">
            {recommended.length === 0 && <p className="text-xs text-muted">暂无可推荐练习</p>}
            {recommended.map((item) => (
              <button
                key={item.id}
                type="button"
                onClick={() => onPractice(item.problem)}
                className="w-full text-left rounded-xl border border-line bg-black/20 hover:border-blue-500 px-3 py-3 transition"
              >
                <div className="text-sm font-medium">{item.title}</div>
                <div className="mt-1 text-xs text-muted line-clamp-2">{item.problem}</div>
                <div className="mt-2 text-[11px] text-blue-300">{item.reason}</div>
              </button>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
