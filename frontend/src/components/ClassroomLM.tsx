// ClassroomLM.tsx
// Drop-in replacement for your main chat component.
// Assumes backend endpoints: POST /query (RAG), POST /chat (general/math), POST /upload

import { useState, useRef, useEffect, KeyboardEvent } from 'react';
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

// ==================== Component ====================
export default function ClassroomLM() {
  const [conversations, setConversations] = useState<Conversation[]>(() => [
    {
      id: 'seed-1',
      title: "Newton's laws & friction problem",
      messages: [],
      updatedAt: Date.now(),
    },
  ]);
  const [activeId, setActiveId] = useState<string>('seed-1');
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  const active = conversations.find(c => c.id === activeId);
  const messages = active?.messages ?? [];

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

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
    setTimeout(() => textareaRef.current?.focus(), 0);
  }

  async function sendMessage(overrideText?: string) {
    const text = (overrideText ?? input).trim();
    if (!text || isLoading) return;

    const userMsg: Message = {
      id: `m-${Date.now()}`,
      role: 'user',
      content: text,
    };

    updateActive(c => ({
      ...c,
      title: c.messages.length === 0 ? truncate(text, 40) : c.title,
      messages: [...c.messages, userMsg],
      updatedAt: Date.now(),
    }));

    setInput('');
    if (textareaRef.current) textareaRef.current.style.height = 'auto';
    setIsLoading(true);

    try {
      // Route: RAG endpoint for document-grounded queries.
      // Your backend's /query handler returns {answer, sources, route}
      const res = await fetch(`${API_BASE}/tutor`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversation_history: messages.map(m => ({
            role: m.role === 'ai' ? 'assistant' : 'user',
            content: m.content
          })),
          student_model: {}
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const aiMsg: Message = {
        id: `m-${Date.now()}-ai`,
        role: 'ai',
        content: data.response ?? '(no response)',
        source: (data.decision?.toLowerCase() as MessageSource) ?? 'llm',
        citations: [],
        diagram: data.diagram_image || undefined,
      };
      updateActive(c => ({ ...c, messages: [...c.messages, aiMsg] }));
    } catch (err) {
      const errMsg: Message = {
        id: `m-${Date.now()}-err`,
        role: 'ai',
        content: `Error reaching backend: ${(err as Error).message}. Is \`uvicorn main:app\` running?`,
        source: null,
      };
      updateActive(c => ({ ...c, messages: [...c.messages, errMsg] }));
    } finally {
      setIsLoading(false);
    }
  }

  async function handleUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      await fetch(`${API_BASE}/upload`, { method: 'POST', body: formData });
      // optional: toast success
    } catch (err) {
      console.error('Upload failed', err);
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = '';
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

        <div className="clm-sidebar-footer">
          <button
            className="clm-footer-btn"
            onClick={() => fileInputRef.current?.click()}
          >
            <UploadIcon />
            Upload Materials
          </button>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleUpload}
            style={{ display: 'none' }}
            accept=".pdf,.txt,.md,.png,.jpg,.jpeg"
          />

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
            Qwen 2.5 · RAG ready
          </div>
        </div>

        <div className="clm-messages">
          {messages.length === 0 ? (
            <WelcomeScreen onPick={text => sendMessage(text)} />
          ) : (
            <div className="clm-messages-inner">
              {messages.map(m => (
                <MessageView key={m.id} m={m} />
              ))}
              {isLoading && <TypingBubble />}
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
              <button
                className="clm-icon-btn"
                onClick={() => fileInputRef.current?.click()}
                title="Attach file"
              >
                <AttachIcon />
              </button>
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
    { label: 'Concept', text: 'Explain the difference between static and kinetic friction with an example.' },
    { label: 'Problem', text: 'A 10 kg block on a 30° incline with μ = 0.2 — find the acceleration.' },
    { label: 'Diagram', text: 'Draw a free-body diagram for a pulley system with two masses.' },
    { label: 'Review', text: 'Quiz me on chapter 12 from the uploaded Hibbeler textbook.' },
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

function MessageView({ m }: { m: Message }) {
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
        <div className="clm-msg-content"
          dangerouslySetInnerHTML={{
            __html: m.content
              .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
              .replace(/\*(.*?)\*/g, '<em>$1</em>')
              .replace(/\n/g, '<br/>')
          }}
        />
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
