// Pilot sign-in: a single participant code (e.g. P07), checked against the
// server's allowlist. The code is the only identity the tutor ever sees or
// saves — no name, no email. Styled with the app's own .clm- tokens.
import { useState, type FormEvent } from 'react';
import { PRIVACY_NOTICE } from '@/lib/pilot';
import './ClassroomLM.css';

export default function ParticipantCodeScreen({ apiBase, notice, onAccepted }: {
  apiBase: string;
  // Shown above the field, e.g. when a saved code stopped being accepted.
  notice?: string;
  // role comes from the server; it only changes labels (the server enforces
  // who can see and change what).
  onAccepted: (code: string, role: 'participant' | 'professor') => void;
}) {
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const trimmed = code.trim();
    if (!trimmed || checking) return;
    setChecking(true);
    setError('');
    try {
      const res = await fetch(`${apiBase}/participant/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: trimmed }),
      });
      const data = await res.json().catch(() => null);
      if (res.ok && typeof data?.code === 'string') {
        onAccepted(data.code, data.role === 'professor' ? 'professor' : 'participant');
      } else if (res.status === 401) {
        setError("That code isn't recognized. Check it with your instructor.");
      } else {
        setError('Could not check your code right now. Please try again.');
      }
    } catch {
      setError('Could not reach the tutor. Check your connection and try again.');
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="clm-app clm-gate">
      <form className="clm-gate-card" onSubmit={submit}>
        <div className="clm-brand">
          <div className="clm-brand-mark">C</div>
          <div className="clm-gate-brand-name">ClassroomLM</div>
        </div>
        {notice && <div className="clm-upload-error">{notice}</div>}
        <label className="clm-gate-label" htmlFor="clm-participant-code">
          Participant code
        </label>
        <input
          id="clm-participant-code"
          className="clm-gate-input"
          value={code}
          onChange={e => setCode(e.target.value)}
          placeholder="e.g. P07"
          autoComplete="off"
          autoCapitalize="characters"
          spellCheck={false}
          autoFocus
          maxLength={32}
        />
        {error && <div className="clm-upload-error">{error}</div>}
        <button className="clm-gate-submit" type="submit" disabled={!code.trim() || checking}>
          {checking ? 'Checking…' : 'Start'}
        </button>
        <p className="clm-gate-privacy">{PRIVACY_NOTICE}</p>
      </form>
    </div>
  );
}
