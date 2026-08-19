// ClassroomLM.tsx
// Drop-in replacement for your main chat component.
// Assumes backend endpoints: POST /query (RAG), POST /chat (general/math), POST /upload

import { useState, useRef, useEffect, memo, type KeyboardEvent } from 'react';
import Markdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import './ClassroomLM.css';

// ==================== Types ====================
type MessageSource = 'rag' | 'sympy' | 'llm' | null;

interface Message {
  id: string;
  role: 'user' | 'ai';
  content: string;
  source?: MessageSource;
  citations?: string[];
  diagram?: string;
}

interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

// ==================== Backend config ====================
const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

// ==================== Session persistence ====================
// Conversations (and thus the conversation_history sent to /tutor) are backed
// by sessionStorage so the full accumulated history survives page reloads for
// as long as the browser session (tab) stays open, and is cleared once it is
// closed. All access is wrapped in try/catch so unavailable or full storage
// degrades gracefully to plain in-memory state.
const STORAGE_KEY = 'classroomlm:conversations';
const ACTIVE_KEY = 'classroomlm:activeId';

function defaultConversations(): Conversation[] {
  return [
    {
      id: 'seed-1',
      title: "Newton's laws & friction problem",
      messages: [],
      updatedAt: Date.now(),
    },
  ];
}

function loadConversations(): Conversation[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed as Conversation[];
    }
  } catch {
    // corrupt or unavailable storage — fall through to defaults
  }
  return defaultConversations();
}

function loadActiveId(conversations: Conversation[]): string {
  try {
    const stored = sessionStorage.getItem(ACTIVE_KEY);
    if (stored && conversations.some(c => c.id === stored)) return stored;
  } catch {
    // ignore and fall back to the first conversation
  }
  return conversations[0]?.id ?? 'seed-1';
}

// --- Per-conversation history persistence ---------------------------------
// The conversation_history sent to /tutor/stream is persisted per conversation
// under "conversation_history_{conversationId}" so switching between (or
// reloading) conversations restores each one's own accumulated history.
type HistoryTurn = { role: 'user' | 'assistant'; content: string };

const HISTORY_KEY_PREFIX = 'conversation_history_';

function historyKey(conversationId: string): string {
  return `${HISTORY_KEY_PREFIX}${conversationId}`;
}

function loadHistory(conversationId: string): HistoryTurn[] | null {
  try {
    const raw = sessionStorage.getItem(historyKey(conversationId));
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) return parsed as HistoryTurn[];
    }
  } catch {
    // corrupt or unavailable storage — treat as no stored history
  }
  return null;
}

function saveHistory(conversationId: string, history: HistoryTurn[]): void {
  try {
    sessionStorage.setItem(historyKey(conversationId), JSON.stringify(history));
  } catch {
    // storage full/unavailable — keep going with the in-memory ref
  }
}

function clearHistory(conversationId: string): void {
  try {
    sessionStorage.removeItem(historyKey(conversationId));
  } catch {
    // ignore — non-removed key is harmless
  }
}


type StoredDoc = {
  doc_id: string;
  filename: string;
  words: number;
  extraction_method: string;
};

// ==================== Component ====================
export default function ClassroomLM() {
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string>(() => loadActiveId(loadConversations()));
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [documents, setDocuments] = useState<StoredDoc[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [studentModel, setStudentModel] = useState<object>({});
  const [uploadError, setUploadError] = useState('');
  async function refreshDocuments() {
    try {
      const res = await fetch(`${API_BASE}/documents`);
      if (!res.ok) return;
      const data = await res.json();
      setDocuments(data.documents ?? []);
    } catch {
      // list stays as-is; the sidebar just shows what it last had
    }
  }

  useEffect(() => { refreshDocuments(); }, []);

  const active = conversations.find(c => c.id === activeId);
  const messages = active?.messages ?? [];

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Conversation history sent to /tutor/stream lives in a ref so it persists
  // across re-renders without causing them. It is backed by sessionStorage
  // (per conversation) and appended after each response.
  const conversationHistoryRef = useRef<HistoryTurn[]>([]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  // Persist the accumulated conversations (and the active one) to
  // sessionStorage on every change so history survives reloads within the
  // browser session.
  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    } catch {
      // storage full/unavailable — keep going with in-memory state only
    }
  }, [conversations]);

  useEffect(() => {
    try {
      sessionStorage.setItem(ACTIVE_KEY, activeId);
    } catch {
      // ignore — non-persisted active id still works in-memory
    }
  }, [activeId]);

  // On conversation switch (and on mount, for the initially-active
  // conversation), load the history ref from sessionStorage under
  // "conversation_history_{activeId}" if present; otherwise rebuild it from the
  // conversation's own messages. Depends on activeId ONLY: within a
  // conversation the ref is advanced by sendMessage's append, not rebuilt on
  // every message change.
  useEffect(() => {
    const stored = loadHistory(activeId);
    if (stored) {
      conversationHistoryRef.current = stored;
    } else {
      const msgs = conversations.find(c => c.id === activeId)?.messages ?? [];
      conversationHistoryRef.current = msgs
        .filter(m => m.content.trim() !== '')
        .map(m => ({ role: m.role === 'ai' ? 'assistant' : 'user', content: m.content }));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  // ==================== Handlers ====================
  function updateActive(updater: (c: Conversation) => Conversation) {
    setConversations(prev =>
      prev.map(c => (c.id === activeId ? updater(c) : c))
    );
  }

  function newChat() {
    const id = `c-${Date.now()}`;
    const fresh: Conversation = {
      id,
      title: 'New conversation',
      messages: [],
      updatedAt: Date.now(),
    };
    setConversations(prev => [fresh, ...prev]);
    setActiveId(id);
    // Fresh conversation: empty the ref and drop any stale persisted history.
    conversationHistoryRef.current = [];
    clearHistory(id);
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

async function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || isLoading) return;

    // Read the accumulated history for THIS conversation from the ref (it
    // persists across re-renders without triggering them). This is the full
    // prior history; the current turn is appended to the ref below, only after
    // the response has streamed in.
    const conversationHistory = conversationHistoryRef.current;

    const userMsg: Message = { id: `m-${Date.now()}`, role: 'user', content: text };

    updateActive(c => ({
      ...c,
      title: c.messages.length === 0 ? truncate(text, 40) : c.title,
      messages: [...c.messages, userMsg],
      updatedAt: Date.now(),
    }));

    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setIsLoading(true);

    const aiId = `m-${Date.now()}-ai`;
    const aiMsg: Message = { id: aiId, role: 'ai', content: '', source: 'llm', citations: [] };
    updateActive(c => ({ ...c, messages: [...c.messages, aiMsg] }));

    const patchAi = (patch: Partial<Message>) =>
      updateActive(c => ({
        ...c,
        messages: c.messages.map(m => (m.id === aiId ? { ...m, ...patch } : m)),
      }));

    try {
      const res = await fetch(`${API_BASE}/tutor/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversation_history: conversationHistory,
          student_model: studentModel,
          doc_ids: selectedDocIds,
        }),
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let streamed = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split('\n\n');
        buffer = frames.pop() ?? '';

        for (const frame of frames) {
          const line = frame.trim();
          if (!line.startsWith('data:')) continue;

          let evt: any;
          try {
            evt = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }

          if (evt.type === 'status') {
            if (!streamed) patchAi({ content: evt.text });
          } else if (evt.type === 'meta') {
            if (evt.student_model) setStudentModel(evt.student_model);
            patchAi({
              source: (evt.decision?.toLowerCase() as MessageSource) ?? 'llm',
              diagram: evt.diagram_image || undefined,
            });
          } else if (evt.type === 'token') {
            streamed += evt.text;
            patchAi({ content: streamed });
          } else if (evt.type === 'error') {
            streamed += `\n\n[error: ${evt.text}]`;
            patchAi({ content: streamed });
          }
        }
      }

      if (!streamed) patchAi({ content: '(no response)' });

      // Append this completed turn (user + assistant) to the history ref so the
      // next /tutor/stream request carries the full accumulated history, and
      // persist it under "conversation_history_{activeId}".
      conversationHistoryRef.current = [
        ...conversationHistoryRef.current,
        { role: 'user', content: text },
        { role: 'assistant', content: streamed || '(no response)' },
      ];
      saveHistory(activeId, conversationHistoryRef.current);
    } catch (err) {
      patchAi({
        content: `Error reaching backend: ${(err as Error).message}. Is \`uvicorn main:app\` running?`,
        source: null,
      });
    } finally {
      setIsLoading(false);
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const res = await fetch(`${API_BASE}/documents`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (!res.ok) {
        // The backend sends a human-readable reason in `detail`.
        setUploadError(data.detail ?? `Upload failed (HTTP ${res.status})`);
        return;
      }

      setUploadError('');
      await refreshDocuments();
      // Newly uploaded documents start attached — that is almost always what
      // the person wants right after uploading one.
      setSelectedDocIds(prev => [...prev, data.doc_id]);
    } catch (err) {
      setUploadError(`Upload failed: ${(err as Error).message}`);
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }

  function toggleDoc(docId: string) {
    setSelectedDocIds(prev =>
      prev.includes(docId) ? prev.filter(id => id !== docId) : [...prev, docId]
    );
  }

  async function deleteDoc(docId: string) {
    try {
      await fetch(`${API_BASE}/documents/${docId}`, { method: 'DELETE' });
      setSelectedDocIds(prev => prev.filter(id => id !== docId));
      await refreshDocuments();
    } catch {
      setUploadError('Could not delete that document.');
    }
  }

  // Summarize / quiz results are injected into the chat as AI messages so they
  // reuse the existing message rendering rather than needing their own surface.
  async function runDocAction(docId: string, action: 'summarize' | 'quiz') {
    const doc = documents.find(d => d.doc_id === docId);
    const label = doc?.filename ?? 'document';
    const pendingId = `m-${Date.now()}-doc`;

    updateActive(c => ({
      ...c,
      messages: [...c.messages, {
        id: pendingId,
        role: 'ai',
        content: action === 'quiz'
          ? `Writing a quiz from ${label}…`
          : `Summarizing ${label}…`,
        source: null,
      }],
    }));

    try {
      const body = action === 'quiz'
        ? { doc_ids: [docId], num_questions: 5 }
        : { doc_ids: [docId] };

      const res = await fetch(`${API_BASE}/documents/${action}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail ?? `HTTP ${res.status}`);

      const content = action === 'quiz' ? formatQuiz(data) : data.summary;
      updateActive(c => ({
        ...c,
        messages: c.messages.map(m =>
          m.id === pendingId ? { ...m, content } : m
        ),
      }));
    } catch (err) {
      updateActive(c => ({
        ...c,
        messages: c.messages.map(m =>
          m.id === pendingId
            ? { ...m, content: `Could not ${action} ${label}: ${(err as Error).message}` }
            : m
        ),
      }));
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function autoResize(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }

  // ==================== Render ====================
  return (
    <div className="clm-app">
      {/* ---------------- Sidebar ---------------- */}
      <aside className="clm-sidebar">
        <div className="clm-sidebar-header">
          <div className="clm-brand">
            <div className="clm-brand-mark">C</div>
            <div className="clm-brand-text">
              <div className="clm-brand-name">ClassroomLM</div>
              <div className="clm-brand-sub">UTEP · Dynamics</div>
            </div>
          </div>
          <button className="clm-new-chat" onClick={newChat}>
            <PlusIcon />
            New Conversation
          </button>
        </div>

        <div className="clm-convo-section">
          <div className="clm-section-label">Recent</div>
          {conversations.map(c => (
            <div
              key={c.id}
              className={`clm-convo-item ${c.id === activeId ? 'active' : ''}`}
              onClick={() => setActiveId(c.id)}
            >
              <MessageIcon />
              <span className="clm-convo-title">{c.title}</span>
            </div>
          ))}
        </div>

<div className="clm-sources-section">
          <div className="clm-section-label">
            Sources
            {selectedDocIds.length > 0 && (
              <span className="clm-attached-count">
                {selectedDocIds.length} attached
              </span>
            )}
          </div>

          {documents.length === 0 && !isUploading && (
            <div className="clm-sources-empty">
              No documents yet. Upload lecture notes, a homework page, or a photo
              of your work.
            </div>
          )}

          {documents.map(d => (
            <div key={d.doc_id} className="clm-source-item">
              <label className="clm-source-label">
                <input
                  type="checkbox"
                  checked={selectedDocIds.includes(d.doc_id)}
                  onChange={() => toggleDoc(d.doc_id)}
                />
                <span className="clm-source-name" title={d.filename}>
                  {d.filename}
                </span>
              </label>
              <div className="clm-source-meta">
                {d.words} words
                {d.extraction_method === 'vision' && ' · transcribed'}
              </div>
              <div className="clm-source-actions">
                <button onClick={() => runDocAction(d.doc_id, 'summarize')}>
                  Summarize
                </button>
                <button onClick={() => runDocAction(d.doc_id, 'quiz')}>
                  Quiz
                </button>
                <button onClick={() => deleteDoc(d.doc_id)}>Delete</button>
              </div>
            </div>
          ))}
        </div>

        <div className="clm-sidebar-footer">
          <button
            className="clm-footer-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading}
          >
            <UploadIcon />
            {isUploading ? 'Reading document…' : 'Upload Materials'}
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleUpload}
            style={{ display: 'none' }}
            accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.gif,.webp"
          />

          {uploadError && (
            <div className="clm-upload-error">{uploadError}</div>
          )}

          <div className="clm-user-card">
            <div className="clm-avatar">E</div>
            <div className="clm-user-meta">
              <div className="clm-user-name">Emu</div>
              <div className="clm-user-role">Undergraduate · UTEP</div>
            </div>
          </div>
        </div>
      </aside>

      {/* ---------------- Main ---------------- */}
      <main className="clm-main">
        <div className="clm-chat-header">
          <div className="clm-chat-title">
            {active?.title ?? 'New conversation'}
            <span className="clm-subject-tag">Dynamics</span>
          </div>
          <div className="clm-mode-pill">
            <span className="clm-mode-dot" />
            Claude Sonnet · RAG ready
          </div>
        </div>

        <div className="clm-messages">
          {messages.length === 0 ? (
            <WelcomeScreen onPick={text => sendMessage(text)} />
          ) : (
            <div className="clm-messages-inner">
              {(() => {
                const visible = messages.filter(m => !(m.role === 'ai' && m.content === ''));
                return visible.map((m, i) => (
                  <MessageView
                    key={m.id}
                    m={m}
                    isStreaming={isLoading && i === visible.length - 1 && m.role === 'ai'}
                  />
                ));
              })()}
              {isLoading && messages[messages.length - 1]?.content === '' && <TypingBubble />}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="clm-composer-wrap">
          <div className="clm-composer">
            <textarea
              ref={textareaRef}
              className="clm-composer-textarea"
              placeholder="Ask anything about Dynamics…"
              rows={1}
              value={input}
              onChange={e => {
                setInput(e.target.value);
                autoResize(e.target);
              }}
              onKeyDown={onKeyDown}
              disabled={isLoading}
            />
            <div className="clm-composer-actions">
              {selectedDocIds.length > 0 && (
                <span className="clm-attach-indicator" title="Attached sources">
                  <AttachIcon />
                  {selectedDocIds.length}
                </span>
              )}
              <button
                className="clm-send-btn"
                onClick={() => sendMessage()}
                disabled={!input.trim() || isLoading}
              >
                <SendIcon />
              </button>
            </div>
          </div>
          <div className="clm-composer-foot">
            ClassroomLM is a research prototype — always verify answers with course materials.
          </div>
        </div>
      </main>
    </div>
  );
}

// ==================== Subcomponents ====================
function WelcomeScreen({ onPick }: { onPick: (text: string) => void }) {
  const suggestions = [
    { label: 'Concept', text: 'What is the difference between angular velocity and angular acceleration?' },
    { label: 'Problem', text: 'A 12 kg block slides down a 25 degree frictionless incline from rest. Find its acceleration and the normal force. Show me a worked example.' },
    { label: 'Draw', text: 'Draw the free-body diagram for a block on a rough incline being pushed up the slope.' },
    { label: 'Practice', text: 'Make me a practice problem about projectile motion.' },
  ];
  return (
    <div className="clm-welcome">
      <div className="clm-welcome-icon">C</div>
      <h1>
        How can I help with <em>Dynamics</em> today?
      </h1>
      <p>
        Ask about Newton's laws, free-body diagrams, rigid body motion, or upload
        a homework problem. I'll use your professor's approved materials when I can.
      </p>
      <div className="clm-suggestion-grid">
        {suggestions.map(s => (
          <button
            key={s.label}
            className="clm-suggestion"
            onClick={() => onPick(s.text)}
          >
            <div className="clm-suggestion-label">{s.label}</div>
            <div className="clm-suggestion-text">{s.text}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// Completed assistant messages render through the Markdown + remark-math +
// rehype-katex pipeline. Memoized on `content` so unrelated re-renders don't
// re-parse it. rehype-katex runs with throwOnError:false so one malformed
// expression can't break the rest of the message. remark-math leaves math
// inside code blocks/inline code untouched, and treats a lone `$20` as text.
const MarkdownMessage = memo(function MarkdownMessage({ content }: { content: string }) {
  return (
    <Markdown
      remarkPlugins={[remarkMath]}
      rehypePlugins={[[rehypeKatex, { throwOnError: false }]]}
    >
      {content}
    </Markdown>
  );
});

function MessageView({ m, isStreaming }: { m: Message; isStreaming?: boolean }) {
  // Render the full Markdown/KaTeX pipeline only for COMPLETED assistant
  // messages. While streaming (and for user messages) show cheap plain text so
  // math isn't re-parsed on every token and partial LaTeX doesn't flicker.
  const renderAsMarkdown = m.role === 'ai' && !isStreaming;
  return (
    <div className={`clm-message ${m.role}`}>
      <div className="clm-msg-avatar">{m.role === 'user' ? 'E' : 'C'}</div>
      <div className="clm-msg-body">
        <div className="clm-msg-author">
          {m.role === 'user' ? 'You' : 'ClassroomLM'}
          {m.role === 'ai' && m.source && (
            <span className={`clm-msg-source-tag ${m.source}`}>
              {m.source === 'rag' ? 'RAG' : m.source === 'sympy' ? 'SymPy' : 'LLM'}
            </span>
          )}
        </div>
        <div className="clm-msg-content">
          {renderAsMarkdown
            ? <MarkdownMessage content={m.content} />
            : <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>}
        </div>
        {m.diagram && (
          <img
            src={`data:image/png;base64,${m.diagram}`}
            alt="Free Body Diagram"
            style={{
              marginTop: '16px',
              maxWidth: '100%',
              borderRadius: '8px',
              border: '1px solid rgba(15,15,15,0.08)',
            }}
          />
        )}
      </div>
    </div>
  );
}

function TypingBubble() {
  return (
    <div className="clm-message ai">
      <div className="clm-msg-avatar">C</div>
      <div className="clm-msg-body">
        <div className="clm-typing">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}

// ==================== Icons (inline to avoid a lib dep) ====================
const PlusIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round">
    <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
  </svg>
);
const MessageIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);
const UploadIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="17 8 12 3 7 8" />
    <line x1="12" y1="3" x2="12" y2="15" />
  </svg>
);
const AttachIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  </svg>
);
const SendIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);

// ==================== Utils ====================
function truncate(s: string, n: number) {
  return s.length <= n ? s : s.slice(0, n - 1) + '…';
}


function formatQuiz(data: any): string {
  const lines: string[] = [];
  if (data.topic) lines.push(`**Quiz: ${data.topic}**`);
  (data.questions ?? []).forEach((q: any, i: number) => {
    lines.push('');
    lines.push(`**${i + 1}. ${q.question}**`);
    q.options.forEach((opt: string, j: number) => {
      lines.push(`${String.fromCharCode(65 + j)}. ${opt}`);
    });
    lines.push(`*Answer: ${String.fromCharCode(65 + q.correct_index)} — ${q.explanation}*`);
  });
  if (data.rejected?.length) {
    lines.push('');
    lines.push(`*${data.rejected.length} question(s) were dropped in validation.*`);
  }
  return lines.join('\n');
}
