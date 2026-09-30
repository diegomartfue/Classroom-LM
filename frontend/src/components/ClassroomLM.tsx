// ClassroomLM.tsx
// Drop-in replacement for your main chat component.
// Assumes backend endpoints: POST /tutor/stream (tutoring), POST /documents (uploads)

import { useState, useRef, useEffect, useMemo, useCallback, useSyncExternalStore, memo, type KeyboardEvent } from 'react';
import Markdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import DOMPurify from 'dompurify';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog';
import { useIsMobile } from '@/hooks/use-mobile';
import { PARTICIPANT_HEADER, PRIVACY_NOTICE } from '@/lib/pilot';
import { SmoothReveal, prepareStreamingBlocks } from '@/lib/smoothStream';
import ParticipantCodeScreen from './ParticipantCodeScreen';
import 'katex/dist/katex.min.css';
import './ClassroomLM.css';

// A diagram the student clicked to view full size (Feature: diagram zoom).
type ZoomedDiagram = { kind: 'svg' | 'png'; content: string } | null;

// ==================== Types ====================
type MessageSource = 'rag' | 'sympy' | 'llm' | null;

interface Message {
  id: string;
  role: 'user' | 'ai';
  content: string;
  source?: MessageSource;
  citations?: string[];
  diagram?: string;
  diagramSvg?: string;
  // Set on an AI message that failed (network error or a mid-stream SSE
  // error event) instead of ever going blank. retryText is the student's
  // original message, so the Retry button can resend it verbatim.
  failed?: boolean;
  retryText?: string;
  // Backend turn number for this AI reply (matches OrchestratorAgent's own
  // counting: how many user messages preceded it), so a thumbs up/down can
  // be attributed to the right turn in state/feedback.jsonl.
  turnNumber?: number;
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

// --- Participant code (pilot) -----------------------------------------
// The student's only identity: a pilot code like P07, checked against the
// server's allowlist (backend/participants.py) and sent as the
// X-Participant-Code header on every request. The server saves records
// under this code and nothing else — no name, no email. Remembered in
// localStorage so students don't retype it.
const PARTICIPANT_CODE_KEY = 'classroomlm:participantCode';
// Before participant codes, a random per-browser id lived here. Removed on
// load so nothing keeps sending or storing it.
const LEGACY_STUDENT_ID_KEY = 'classroomlm:studentId';
const PRIVACY_SEEN_KEY = 'classroomlm:privacyNoticeSeen';
const PARTICIPANT_ROLE_KEY = 'classroomlm:participantRole';

type Role = 'participant' | 'professor';

function loadRole(): Role {
  try {
    return localStorage.getItem(PARTICIPANT_ROLE_KEY) === 'professor' ? 'professor' : 'participant';
  } catch {
    return 'participant';
  }
}

function saveRole(role: Role | null): void {
  try {
    if (role) localStorage.setItem(PARTICIPANT_ROLE_KEY, role);
    else localStorage.removeItem(PARTICIPANT_ROLE_KEY);
  } catch {
    // label-only; the server enforces roles
  }
}

function loadParticipantCode(): string {
  try {
    localStorage.removeItem(LEGACY_STUDENT_ID_KEY);
    return localStorage.getItem(PARTICIPANT_CODE_KEY) ?? '';
  } catch {
    return '';
  }
}

function saveParticipantCode(code: string): void {
  try {
    if (code) localStorage.setItem(PARTICIPANT_CODE_KEY, code);
    else localStorage.removeItem(PARTICIPANT_CODE_KEY);
  } catch {
    // storage unavailable — the code still works for this page load
  }
}

function loadPrivacySeen(): boolean {
  try {
    return localStorage.getItem(PRIVACY_SEEN_KEY) === '1';
  } catch {
    return false;
  }
}

function savePrivacySeen(): void {
  try {
    localStorage.setItem(PRIVACY_SEEN_KEY, '1');
  } catch {
    // shown again next load — harmless
  }
}

// --- Hint ladder level (pilot item 7) -----------------------------------
// Tracked per conversation (there's no separate "problem id" the frontend
// has visibility into — one conversation is treated as one problem in
// progress, matching how item 6's turn_number tracking already treats a
// conversation as the natural unit). Persisted in sessionStorage, same tier
// as conversation history, so a reload mid-hinting doesn't silently reset
// the ladder back to level 1.
const HINT_LEVEL_KEY_PREFIX = 'classroomlm:hintLevel:';
const MAX_HINT_LEVEL = 4;

function hintLevelKey(conversationId: string): string {
  return `${HINT_LEVEL_KEY_PREFIX}${conversationId}`;
}

function loadHintLevel(conversationId: string): number {
  try {
    const raw = sessionStorage.getItem(hintLevelKey(conversationId));
    const n = raw ? parseInt(raw, 10) : 0;
    return Number.isFinite(n) && n > 0 ? Math.min(n, MAX_HINT_LEVEL) : 0;
  } catch {
    return 0;
  }
}

function saveHintLevel(conversationId: string, level: number): void {
  try {
    sessionStorage.setItem(hintLevelKey(conversationId), String(level));
  } catch {
    // storage full/unavailable — the in-memory state still works this turn
  }
}

// --- Show-your-work checker (pilot item 9) ---------------------------------
// The parsed problem from the latest PROBLEM turn's "meta" event, kept per
// conversation and sent back verbatim to /check-work. The backend looks the
// solver's answers up itself (agents/solution_cache.py), so no answer is
// ever stored here.
const PROBLEM_KEY_PREFIX = 'classroomlm:problem:';

type ParsedProblem = Record<string, unknown>;

function hasProblemShape(value: unknown): value is ParsedProblem {
  if (!value || typeof value !== 'object') return false;
  const v = value as ParsedProblem;
  return (Array.isArray(v.givens) && v.givens.length > 0)
    || (Array.isArray(v.unknowns_requested) && v.unknowns_requested.length > 0);
}

function loadProblem(conversationId: string): ParsedProblem | null {
  try {
    const raw = sessionStorage.getItem(`${PROBLEM_KEY_PREFIX}${conversationId}`);
    const parsed = raw ? JSON.parse(raw) : null;
    return hasProblemShape(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function saveProblem(conversationId: string, problem: ParsedProblem): void {
  try {
    sessionStorage.setItem(`${PROBLEM_KEY_PREFIX}${conversationId}`, JSON.stringify(problem));
  } catch {
    // storage full/unavailable — the in-memory state still works this session
  }
}

type LineStatus = 'correct' | 'incorrect' | 'unverifiable' | 'invalid' | 'defined';

type LineResult = {
  line: string;
  status: LineStatus;
  detail: string;
};

type WorkCheck = {
  results: LineResult[];
  firstWrongIndex: number | null;
  allCorrect: boolean;
};

const HINT_LEVEL_PROMPTS: Record<number, string> = {
  1: 'Can I get a hint?',
  2: 'Can I get a bigger hint?',
  3: 'Can you show me one worked step?',
  4: "I've worked through the hints — can you show me the answer?",
};

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
  // "shared": professor course material everyone sees; "private": this
  // participant's own upload, visible only to them (enforced server-side).
  scope: 'shared' | 'private';
  mine: boolean;
};

// --- Sidebar collapsed-state persistence -----------------------------------
// Unlike conversations/history (sessionStorage — per browser session), the
// collapsed/expanded choice is a durable UI preference, so it survives
// reloads and new sessions via localStorage.
const SIDEBAR_COLLAPSED_KEY = 'classroomlm:sidebarCollapsed';

function loadSidebarCollapsed(): boolean {
  try {
    return localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1';
  } catch {
    return false;
  }
}

// ==================== Component ====================
// Sign-in gate: nothing below talks to the API until the server has
// accepted a participant code. A 401 from any later request (code removed
// from the allowlist) sends the student back here.
export default function ClassroomLM() {
  const [participantCode, setParticipantCode] = useState<string>(loadParticipantCode);
  const [role, setRole] = useState<Role>(loadRole);
  const [gateNotice, setGateNotice] = useState('');

  if (!participantCode) {
    return (
      <ParticipantCodeScreen
        apiBase={API_BASE}
        notice={gateNotice}
        onAccepted={(code, acceptedRole) => {
          saveParticipantCode(code);
          saveRole(acceptedRole);
          setRole(acceptedRole);
          setGateNotice('');
          setParticipantCode(code);
        }}
      />
    );
  }

  return (
    <TutorApp
      participantCode={participantCode}
      role={role}
      onSignOut={rejected => {
        saveParticipantCode('');
        saveRole(null);
        setGateNotice(rejected
          ? "Your participant code wasn't accepted. Please enter it again."
          : '');
        setParticipantCode('');
      }}
    />
  );
}

function TutorApp({ participantCode, role, onSignOut }: {
  participantCode: string;
  role: Role;
  onSignOut: (rejected: boolean) => void;
}) {
  const [conversations, setConversations] = useState<Conversation[]>(loadConversations);
  const [activeId, setActiveId] = useState<string>(() => loadActiveId(loadConversations()));
  // Stable per-browser identity (see loadStudentId above); computed once.
  const [privacySeen, setPrivacySeen] = useState<boolean>(loadPrivacySeen);

  // Every API call goes through here so the participant code is always
  // attached, and a rejected code always returns the student to sign-in.
  async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
    const headers = new Headers(init.headers);
    headers.set(PARTICIPANT_HEADER, participantCode);
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers });
    if (res.status === 401) onSignOut(true);
    return res;
  }

  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [selectedDocIds, setSelectedDocIds] = useState<string[]>([]);
  const [documents, setDocuments] = useState<StoredDoc[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [studentModel, setStudentModel] = useState<object>({});
  const [uploadError, setUploadError] = useState('');
  // Hint ladder level for the active conversation (item 7); reloaded
  // whenever the student switches conversations.
  const [hintLevel, setHintLevel] = useState<number>(() => loadHintLevel(activeId));
  useEffect(() => {
    setHintLevel(loadHintLevel(activeId));
  }, [activeId]);

  // Show-your-work checker (item 9): the active conversation's problem, the
  // panel's text, and the last check result. Reset on conversation switch.
  const [problem, setProblem] = useState<ParsedProblem | null>(() => loadProblem(activeId));
  const [workOpen, setWorkOpen] = useState(false);
  const [workText, setWorkText] = useState('');
  const [workCheck, setWorkCheck] = useState<WorkCheck | null>(null);
  const [workError, setWorkError] = useState('');
  const [isChecking, setIsChecking] = useState(false);
  useEffect(() => {
    setProblem(loadProblem(activeId));
    setWorkOpen(false);
    setWorkText('');
    setWorkCheck(null);
    setWorkError('');
  }, [activeId]);

  // ---------------- Sidebar: collapse (desktop) / drawer (mobile) ----------
  const isMobile = useIsMobile();
  const [sidebarCollapsed, setSidebarCollapsed] = useState<boolean>(loadSidebarCollapsed);
  const [mobileDrawerOpen, setMobileDrawerOpen] = useState(false);
  // The diagram (if any) currently open full-size in the zoom modal.
  const [zoomedDiagram, setZoomedDiagram] = useState<ZoomedDiagram>(null);
  // The reply currently streaming in. Its text lives in the SmoothReveal
  // store, not in `conversations`, so each chunk re-renders only that one
  // message (and doesn't re-serialize every conversation to sessionStorage).
  // Set once, on the first token; the final text is committed to
  // `conversations` in a single update when the stream ends.
  const [liveStream, setLiveStream] = useState<{ id: string; reveal: SmoothReveal } | null>(null);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? '1' : '0');
    } catch {
      // storage full/unavailable — the in-memory state still works this session
    }
  }, [sidebarCollapsed]);

  function toggleSidebar() {
    if (isMobile) setMobileDrawerOpen(o => !o);
    else setSidebarCollapsed(c => !c);
  }

  // Cmd/Ctrl+B toggles the sidebar globally, and Escape closes the mobile
  // drawer — both work regardless of where focus currently is.
  useEffect(() => {
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'b') {
        e.preventDefault();
        toggleSidebar();
      } else if (e.key === 'Escape' && isMobile && mobileDrawerOpen) {
        setMobileDrawerOpen(false);
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isMobile, mobileDrawerOpen]);

  // A conversation switch always closes the mobile drawer (it never makes
  // sense to keep it open once the pick has been made); harmless on desktop,
  // where mobileDrawerOpen is never true.
  function selectConversation(id: string) {
    setActiveId(id);
    setMobileDrawerOpen(false);
  }

  async function refreshDocuments() {
    try {
      const res = await apiFetch(`/documents`);
      if (!res.ok) return;
      const data = await res.json();
      setDocuments(data.documents ?? []);
    } catch {
      // list stays as-is; the sidebar just shows what it last had
    }
  }

  // Mount-only: participantCode is fixed for TutorApp's lifetime (changing
  // it unmounts TutorApp), so refreshDocuments never goes stale.
  // eslint-disable-next-line react-hooks/exhaustive-deps
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

async function sendMessage(overrideText?: string, hintLevel?: number) {
    const text = (overrideText ?? input).trim();
    if (!text || isLoading) return;

    // Snapshot the accumulated history for THIS conversation from the ref (it
    // persists across re-renders without triggering them). Copying into a new
    // array decouples the outgoing request payload from any later mutation of
    // the ref (e.g. a conversation switch) while this request is in flight.
    // This is the full prior history; the current turn is appended to the ref
    // below, only after the response has streamed in.
    const historySnapshot = [...conversationHistoryRef.current];

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
    // Matches OrchestratorAgent's own turn_number counting exactly:
    // historySnapshot is precisely what's sent as conversation_history for
    // this turn, before the current user message is appended to it.
    const turnNumber = historySnapshot.filter(m => m.role === 'user').length;
    const aiMsg: Message = { id: aiId, role: 'ai', content: '', source: 'llm', citations: [], turnNumber };
    updateActive(c => ({ ...c, messages: [...c.messages, aiMsg] }));
    let failed = false;
    let reveal: SmoothReveal | null = null;

    const patchAi = (patch: Partial<Message>) =>
      updateActive(c => ({
        ...c,
        messages: c.messages.map(m => (m.id === aiId ? { ...m, ...patch } : m)),
      }));

    try {
      console.log(
        `[ClassroomLM] /tutor/stream: sending ${historySnapshot.length} prior message(s) as conversation_history`
      );
      const res = await apiFetch(`/tutor/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          conversation_history: historySnapshot,
          student_model: studentModel,
          doc_ids: selectedDocIds,
          session_id: activeId,
          ...(hintLevel !== undefined ? { hint_level: hintLevel } : {}),
        }),
      });

      if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let streamed = '';
      reveal = new SmoothReveal();

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
            if (hasProblemShape(evt.parsed_input)) {
              setProblem(evt.parsed_input);
              saveProblem(activeId, evt.parsed_input);
            }
            patchAi({
              source: (evt.decision?.toLowerCase() as MessageSource) ?? 'llm',
              diagram: evt.diagram_image || undefined,
              diagramSvg: evt.diagram_svg || undefined,
            });
          } else if (evt.type === 'token') {
            if (!streamed && evt.text) setLiveStream({ id: aiId, reveal });
            streamed += evt.text;
            reveal.push(evt.text);
          } else if (evt.type === 'error') {
            // The backend already sends a safe, friendly message (see
            // main.py's tutor_stream_endpoint) — show it as-is rather than
            // appending a bracketed [error: ...] fragment onto whatever
            // partial text streamed before the failure, and mark the
            // message failed so it gets a Retry button instead of ever
            // reaching future turns as if it were a real reply.
            failed = true;
            reveal.stop();
            setLiveStream(null);
            patchAi({ content: evt.text, failed: true, retryText: text });
          }
        }
      }

      if (failed) return;  // no history append — see the finally block below

      // Stream finished: show everything still buffered at once and commit
      // the final text to the conversation in one state update.
      reveal.flush();
      patchAi({ content: streamed || '(no response)' });
      setLiveStream(null);

      // Append this completed turn (user + assistant) to the history in a
      // single operation, building on the snapshot taken before the request so
      // the accumulated history stays correct even if the ref was reset by a
      // conversation switch while this request was in flight. Persist it under
      // "conversation_history_{activeId}" right after the append.
      conversationHistoryRef.current = [
        ...historySnapshot,
        { role: 'user', content: text },
        { role: 'assistant', content: streamed || '(no response)' },
      ];
      saveHistory(activeId, conversationHistoryRef.current);
    } catch (err) {
      // Network/fetch failure (backend unreachable, non-OK status, etc.) —
      // same treatment as a mid-stream SSE error: a friendly message and a
      // Retry button, never appended to conversation history. The raw
      // error still goes to the console for local debugging — just never
      // to the student.
      console.error('[ClassroomLM] /tutor/stream failed:', err);
      reveal?.stop();
      setLiveStream(null);
      patchAi({
        content: "Something went wrong reaching the tutor. Check your connection and try again.",
        source: null,
        failed: true,
        retryText: text,
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

      const res = await apiFetch(`/documents`, {
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

  // Thumbs up/down on a tutor reply. Pure file-based storage on the backend
  // (feedback_store.py), no LLM involved. Fire-and-forget from the UI's
  // point of view — MessageView already shows the rating optimistically;
  // this just needs to not silently crash if it fails.
  async function sendFeedback(m: Message, rating: 'up' | 'down') {
    if (m.turnNumber === undefined) return;
    try {
      await apiFetch(`/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: activeId,
          turn_number: m.turnNumber,
          rating,
        }),
      });
    } catch {
      toast.error('Could not record feedback.');
    }
  }

  // Stable wrappers for MessageView's callbacks, so the memoized MessageView
  // doesn't re-render every past message whenever TutorApp re-renders.
  const sendMessageRef = useRef(sendMessage);
  const sendFeedbackRef = useRef(sendFeedback);
  sendMessageRef.current = sendMessage;
  sendFeedbackRef.current = sendFeedback;
  const retryMessage = useCallback((text: string) => { sendMessageRef.current(text); }, []);
  const rateMessage = useCallback(
    (m: Message, rating: 'up' | 'down') => { sendFeedbackRef.current(m, rating); }, []);

  // Hint ladder button (item 7): each tap goes one level further — 1 nudge,
  // 2 bigger hint, 3 one worked step, 4 the answer — tracked per
  // conversation and sent as hint_level so the backend handles it
  // deterministically (see OrchestratorAgent._run_turn) rather than relying
  // on the Planner's own judgment about when the student's stuck enough.
  function requestHint() {
    if (isLoading) return;
    const nextLevel = Math.min(hintLevel + 1, MAX_HINT_LEVEL);
    setHintLevel(nextLevel);
    saveHintLevel(activeId, nextLevel);
    sendMessage(HINT_LEVEL_PROMPTS[nextLevel], nextLevel);
  }

  // Show-your-work checker (item 9): one equation per line, each checked
  // with SymPy on the backend against the current problem. The first wrong
  // line is highlighted; lines that only reference unknowns the tutor can't
  // verify yet come back as "can't check" rather than wrong.
  async function checkWork() {
    const lines = workText.split('\n').map(l => l.trim()).filter(Boolean);
    if (!problem || lines.length === 0 || isChecking) return;
    setIsChecking(true);
    setWorkError('');
    try {
      const res = await apiFetch(`/check-work`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // Ties the check to the tutor turn it followed, for the research
        // export (scripts/export_conversations.py).
        body: JSON.stringify({
          lines,
          parsed_input: problem,
          session_id: activeId,
          turn_number: [...messages].reverse().find(m => m.turnNumber !== undefined)?.turnNumber,
        }),
      });
      const data = await res.json().catch(() => null);
      if (!res.ok || !data) {
        setWorkError(typeof data?.detail === 'string'
          ? data.detail
          : 'Could not check your work right now. Please try again.');
        return;
      }
      setWorkCheck({
        results: data.results,
        firstWrongIndex: data.first_wrong_index,
        allCorrect: data.all_correct,
      });
    } catch (err) {
      console.error(err);
      setWorkError('Could not reach the tutor. Check your connection and try again.');
    } finally {
      setIsChecking(false);
    }
  }

  async function deleteDoc(docId: string) {
    try {
      await apiFetch(`/documents/${docId}`, { method: 'DELETE' });
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

      const res = await apiFetch(`/documents/${action}`, {
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
  const sidebarClassName = [
    'clm-sidebar',
    isMobile ? 'clm-sidebar--mobile' : '',
    isMobile && mobileDrawerOpen ? 'clm-sidebar--drawer-open' : '',
    !isMobile && sidebarCollapsed ? 'clm-sidebar--collapsed' : '',
  ].filter(Boolean).join(' ');
  const sidebarExpanded = isMobile ? mobileDrawerOpen : !sidebarCollapsed;

  return (
    <div className="clm-app">
      {/* Mobile-only backdrop: tapping it closes the drawer, same as Escape. */}
      {isMobile && mobileDrawerOpen && (
        <div
          className="clm-sidebar-backdrop"
          onClick={() => setMobileDrawerOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ---------------- Sidebar ---------------- */}
      <aside id="clm-sidebar" className={sidebarClassName}>
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
              onClick={() => selectConversation(c.id)}
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
              {role === 'professor'
                ? 'No course material yet. What you upload here is shared with every participant.'
                : 'No documents yet. Upload notes, a homework page, or a photo of your work. Only you can see your uploads.'}
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
                {d.scope === 'shared' ? 'Course material' : 'Only you'}
                {' · '}{d.words} words
                {d.extraction_method === 'vision' && ' · transcribed'}
              </div>
              <div className="clm-source-actions">
                <button onClick={() => runDocAction(d.doc_id, 'summarize')}>
                  Summarize
                </button>
                <button onClick={() => runDocAction(d.doc_id, 'quiz')}>
                  Quiz
                </button>
                {d.mine && (
                  <button onClick={() => deleteDoc(d.doc_id)}>Delete</button>
                )}
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
            {isUploading
              ? 'Reading document…'
              : role === 'professor' ? 'Upload shared material' : 'Upload my materials'}
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
            <div className="clm-avatar">{participantCode.charAt(0)}</div>
            <div className="clm-user-meta">
              <div className="clm-user-name">{participantCode}</div>
              <div className="clm-user-role">
                {role === 'professor' ? 'Professor' : 'Pilot participant'}
              </div>
            </div>
            <button
              className="clm-change-code"
              onClick={() => onSignOut(false)}
              title="Use a different participant code"
            >
              Change
            </button>
          </div>
        </div>
      </aside>

      {/* ---------------- Main ---------------- */}
      <main className="clm-main">
        <div className="clm-chat-header">
          <div className="clm-header-left">
            <button
              className="clm-sidebar-toggle"
              onClick={toggleSidebar}
              aria-expanded={sidebarExpanded}
              aria-controls="clm-sidebar"
              aria-label={sidebarExpanded ? 'Collapse sidebar' : 'Expand sidebar'}
              title={`${sidebarExpanded ? 'Collapse' : 'Expand'} sidebar (Ctrl/⌘+B)`}
            >
              <SidebarToggleIcon />
            </button>
            <div className="clm-chat-title">
              {active?.title ?? 'New conversation'}
              <span className="clm-subject-tag">Dynamics</span>
            </div>
          </div>
          <div className="clm-mode-pill">
            <span className="clm-mode-dot" />
            Claude · Ready
          </div>
        </div>

        <div className="clm-messages">
          {messages.length === 0 ? (
            <WelcomeScreen onPick={text => sendMessage(text)} />
          ) : (
            <div className="clm-messages-inner">
              {(() => {
                const visible = messages.filter(
                  m => !(m.role === 'ai' && m.content === '' && m.id !== liveStream?.id));
                return visible.map((m, i) => (
                  <MessageView
                    key={m.id}
                    m={m}
                    isStreaming={isLoading && i === visible.length - 1 && m.role === 'ai'}
                    live={liveStream?.id === m.id ? liveStream.reveal : undefined}
                    onZoom={setZoomedDiagram}
                    onRetry={retryMessage}
                    onFeedback={rateMessage}
                  />
                ));
              })()}
              {isLoading && !liveStream && messages[messages.length - 1]?.content === '' && <TypingBubble />}
              <div ref={messagesEndRef} />
            </div>
          )}
        </div>

        <div className="clm-composer-wrap">
          {!privacySeen && (
            <div className="clm-privacy-notice" role="note">
              <span>{PRIVACY_NOTICE}</span>
              <button
                onClick={() => { savePrivacySeen(); setPrivacySeen(true); }}
                aria-label="Dismiss notice"
              >
                Got it
              </button>
            </div>
          )}
          {workOpen && problem && (
            <WorkPanel
              text={workText}
              onTextChange={text => { setWorkText(text); setWorkCheck(null); }}
              check={workCheck}
              error={workError}
              isChecking={isChecking}
              onCheck={checkWork}
              onClose={() => setWorkOpen(false)}
            />
          )}
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
              {problem && (
                <button
                  className={`clm-hint-btn${workOpen ? ' clm-hint-btn-active' : ''}`}
                  onClick={() => setWorkOpen(open => !open)}
                  aria-expanded={workOpen}
                  title="Check your equations line by line"
                >
                  <CheckWorkIcon />
                  Check work
                </button>
              )}
              <button
                className="clm-hint-btn"
                onClick={requestHint}
                disabled={isLoading}
                title={
                  hintLevel >= MAX_HINT_LEVEL
                    ? 'Show the answer again'
                    : `Get a hint (level ${hintLevel + 1} of ${MAX_HINT_LEVEL})`
                }
              >
                <HintIcon />
                Hint{hintLevel > 0 ? ` ${hintLevel}/${MAX_HINT_LEVEL}` : ''}
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

      {/* ---------------- Diagram zoom modal ---------------- */}
      <Dialog
        open={zoomedDiagram !== null}
        onOpenChange={open => { if (!open) setZoomedDiagram(null); }}
      >
        <DialogContent className="w-[92vw] max-w-4xl p-4 sm:p-6">
          <DialogTitle>Diagram</DialogTitle>
          <div className="flex max-h-[80vh] items-center justify-center overflow-auto">
            {zoomedDiagram?.kind === 'svg' ? (
              <div
                className="w-full [&_svg]:h-auto [&_svg]:w-full"
                dangerouslySetInnerHTML={{ __html: zoomedDiagram.content }}
              />
            ) : zoomedDiagram?.kind === 'png' ? (
              <img
                src={`data:image/png;base64,${zoomedDiagram.content}`}
                alt="Free Body Diagram"
                className="h-auto max-w-full"
              />
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
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
// inside code blocks/inline code untouched; the backend prompt tells the
// model to write currency as plain words (never bare "$5"), so no dollar-sign
// escaping is needed here.
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

// The reply that's streaming in right now. Subscribes to the SmoothReveal
// store directly, so each revealed frame re-renders only this component.
// Finished blocks (before the last blank line) are memoized by MarkdownMessage,
// so KaTeX only re-runs on the block still being written, and that block's
// unclosed math shows as plain text until its closing $ or $$ arrives.
function LiveMessageContent({ reveal }: { reveal: SmoothReveal }) {
  const text = useSyncExternalStore(reveal.subscribe, reveal.getSnapshot);
  const blocks = useMemo(() => prepareStreamingBlocks(text), [text]);
  return <>{blocks.map((block, i) => <MarkdownMessage key={i} content={block} />)}</>;
}

const MessageView = memo(function MessageView({
  m, isStreaming, live, onZoom, onRetry, onFeedback,
}: {
  m: Message;
  isStreaming?: boolean;
  live?: SmoothReveal;
  onZoom: (diagram: ZoomedDiagram) => void;
  onRetry: (text: string) => void;
  onFeedback: (m: Message, rating: 'up' | 'down') => void;
}) {
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null);
  function rate(rating: 'up' | 'down') {
    setFeedback(prev => (prev === rating ? null : rating));  // tap again to undo, visually
    onFeedback(m, rating);
  }
  // Completed assistant messages render the full Markdown/KaTeX pipeline. The
  // streaming reply renders through LiveMessageContent instead; status lines
  // before the first token (and user messages) stay plain text.
  const renderAsMarkdown = m.role === 'ai' && !isStreaming;
  // LLM-generated SVG is untrusted markup — sanitize before it ever reaches
  // dangerouslySetInnerHTML. Memoized so re-renders don't re-run DOMPurify.
  const sanitizedDiagramSvg = useMemo(() => {
    if (!m.diagramSvg) return '';
    return DOMPurify.sanitize(m.diagramSvg, { USE_PROFILES: { svg: true, svgFilters: true } }).trim();
  }, [m.diagramSvg]);

  const [copied, setCopied] = useState(false);
  // Copies the raw Markdown/LaTeX SOURCE (m.content, exactly as streamed from
  // the backend, before react-markdown/rehype-katex ever touch it) — never
  // the rendered DOM. Selecting rendered KaTeX output and copying it doubles
  // text (KaTeX renders a visible HTML tree AND a hidden MathML tree for
  // accessibility, and a plain DOM copy grabs both), e.g. "100 N100 N".
  // Copying the source string directly sidesteps that entirely.
  async function copyMessage() {
    try {
      await navigator.clipboard.writeText(m.content);
    } catch {
      // Clipboard API unavailable (older browser, non-secure context) — fall
      // back to the classic hidden-textarea + execCommand trick.
      try {
        const ta = document.createElement('textarea');
        ta.value = m.content;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      } catch {
        toast.error('Could not copy message.');
        return;
      }
    }
    setCopied(true);
    toast.success('Copied to clipboard');
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className={`clm-message ${m.role}${m.failed ? ' failed' : ''}`}>
      <div className="clm-msg-avatar">{m.role === 'user' ? 'E' : 'C'}</div>
      <div className="clm-msg-body">
        <div className="clm-msg-author">
          {m.role === 'user' ? 'You' : 'ClassroomLM'}
          {m.role === 'ai' && m.source && (
            <span className={`clm-msg-source-tag ${m.source}`}>
              {m.source === 'rag' ? 'RAG' : m.source === 'sympy' ? 'SymPy' : 'LLM'}
            </span>
          )}
          {m.role === 'ai' && !isStreaming && m.content && (
            <div className="clm-msg-actions">
              {!m.failed && m.turnNumber !== undefined && (
                <>
                  <button
                    className={`clm-feedback-btn ${feedback === 'up' ? 'active' : ''}`}
                    onClick={() => rate('up')}
                    aria-label="Good response"
                    aria-pressed={feedback === 'up'}
                    title="Good response"
                  >
                    <ThumbsUpIcon />
                  </button>
                  <button
                    className={`clm-feedback-btn ${feedback === 'down' ? 'active' : ''}`}
                    onClick={() => rate('down')}
                    aria-label="Poor response"
                    aria-pressed={feedback === 'down'}
                    title="Poor response"
                  >
                    <ThumbsDownIcon />
                  </button>
                </>
              )}
              {!m.failed && (
                <button
                  className="clm-copy-btn"
                  onClick={copyMessage}
                  aria-label={copied ? 'Copied' : 'Copy message source'}
                  title="Copy raw Markdown/LaTeX source"
                >
                  {copied ? <CheckIcon /> : <CopyIcon />}
                  {copied ? 'Copied' : 'Copy'}
                </button>
              )}
              {m.failed && (
                <button
                  className="clm-copy-btn"
                  onClick={() => m.retryText && onRetry(m.retryText)}
                  aria-label="Retry this message"
                  title="Resend your last message"
                >
                  <RetryIcon />
                  Retry
                </button>
              )}
            </div>
          )}
        </div>
        <div className="clm-msg-content">
          {live
            ? <LiveMessageContent reveal={live} />
            : renderAsMarkdown
              ? <MarkdownMessage content={m.content} />
              : <div style={{ whiteSpace: 'pre-wrap' }}>{m.content}</div>}
        </div>
        {sanitizedDiagramSvg ? (
          <div
            className="clm-msg-diagram clm-diagram-zoomable"
            role="button"
            tabIndex={0}
            aria-label="Open diagram full size"
            onClick={() => onZoom({ kind: 'svg', content: sanitizedDiagramSvg })}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onZoom({ kind: 'svg', content: sanitizedDiagramSvg });
              }
            }}
            style={{
              marginTop: '16px',
              maxWidth: '100%',
              borderRadius: '8px',
              border: '1px solid rgba(15,15,15,0.08)',
              background: '#fff',
              padding: '8px',
              overflowX: 'auto',
            }}
            dangerouslySetInnerHTML={{ __html: sanitizedDiagramSvg }}
          />
        ) : m.diagram && (
          <img
            src={`data:image/png;base64,${m.diagram}`}
            alt="Free Body Diagram"
            className="clm-diagram-zoomable"
            role="button"
            tabIndex={0}
            aria-label="Open diagram full size"
            onClick={() => onZoom({ kind: 'png', content: m.diagram! })}
            onKeyDown={e => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onZoom({ kind: 'png', content: m.diagram! });
              }
            }}
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
});

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
const LINE_STATUS_MARK: Record<LineStatus, { mark: string; label: string }> = {
  correct: { mark: '\u2713', label: 'Correct' },
  incorrect: { mark: '\u2717', label: 'Doesn\u2019t check out' },
  unverifiable: { mark: '?', label: 'Can\u2019t check yet' },
  invalid: { mark: '!', label: 'Couldn\u2019t read this line' },
  defined: { mark: '=', label: 'Saved for later lines' },
};

function WorkPanel({ text, onTextChange, check, error, isChecking, onCheck, onClose }: {
  text: string;
  onTextChange: (text: string) => void;
  check: WorkCheck | null;
  error: string;
  isChecking: boolean;
  onCheck: () => void;
  onClose: () => void;
}) {
  return (
    <section className="clm-work-panel" aria-label="Check your work">
      <div className="clm-work-head">
        <span className="clm-work-title">Check your work</span>
        <span className="clm-work-hint">One equation per line, e.g. N = m*g*cos(30)</span>
        <button className="clm-work-close" onClick={onClose} aria-label="Close" title="Close">
          {'\u00d7'}
        </button>
      </div>
      <textarea
        className="clm-work-input"
        rows={4}
        value={text}
        placeholder={'N = m*g*cos(30)\nf = mu_k*N'}
        spellCheck={false}
        onChange={e => onTextChange(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            onCheck();
          }
        }}
      />
      {check && (
        <ol className="clm-work-results">
          {check.results.map((r, i) => (
            <li
              key={i}
              className={`clm-work-row clm-work-${r.status}${i === check.firstWrongIndex ? ' clm-work-first-wrong' : ''}`}
            >
              <span className="clm-work-mark" title={LINE_STATUS_MARK[r.status].label}>
                {LINE_STATUS_MARK[r.status].mark}
              </span>
              <code className="clm-work-line">{r.line}</code>
              {r.status !== 'correct' && (
                <span className="clm-work-detail">
                  {i === check.firstWrongIndex ? 'First mistake: ' : ''}
                  {r.detail || LINE_STATUS_MARK[r.status].label}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      {check?.allCorrect && (
        <div className="clm-work-summary">Every line you could check is correct.</div>
      )}
      {error && <div className="clm-upload-error">{error}</div>}
      <div className="clm-work-actions">
        <button
          className="clm-hint-btn"
          onClick={onCheck}
          disabled={isChecking || !text.trim()}
        >
          {isChecking ? 'Checking\u2026' : 'Check'}
        </button>
      </div>
    </section>
  );
}

const SendIcon = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
    <line x1="22" y1="2" x2="11" y2="13" />
    <polygon points="22 2 15 22 11 13 2 9 22 2" />
  </svg>
);
const CheckWorkIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 11l3 3L22 4" />
    <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
  </svg>
);
const HintIcon = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M9 18h6" />
    <path d="M10 22h4" />
    <path d="M15.09 14c.18-.98.65-1.74 1.41-2.5A4.65 4.65 0 0 0 18 8 6 6 0 0 0 6 8c0 1 .23 2.23 1.5 3.5.71.71 1.21 1.5 1.41 2.5" />
  </svg>
);
const SidebarToggleIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <line x1="9" y1="4" x2="9" y2="20" />
  </svg>
);
const CopyIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <rect x="9" y="9" width="13" height="13" rx="2" />
    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
  </svg>
);
const CheckIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2} strokeLinecap="round" strokeLinejoin="round">
    <polyline points="20 6 9 17 4 12" />
  </svg>
);
const RetryIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 12a9 9 0 0 1 15.3-6.4L21 8" />
    <path d="M21 3v5h-5" />
    <path d="M21 12a9 9 0 0 1-15.3 6.4L3 16" />
    <path d="M3 21v-5h5" />
  </svg>
);
const ThumbsUpIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M7 10v12" />
    <path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2a3.13 3.13 0 0 1 3 3.88Z" />
  </svg>
);
const ThumbsDownIcon = () => (
  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    <path d="M17 14V2" />
    <path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22a3.13 3.13 0 0 1-3-3.88Z" />
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
