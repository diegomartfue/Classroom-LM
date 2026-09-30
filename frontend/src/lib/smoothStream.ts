// Smooth reveal of streamed tutor text.
//
// Tokens reach the browser in irregular bursts (the model emits unevenly, and
// several SSE frames often land in one network read). Showing each burst as it
// arrives looks choppy, so incoming text goes into a buffer and a
// requestAnimationFrame loop reveals it at a steady pace. The pace grows with
// the backlog, so the display never falls far behind the stream, and flush()
// shows everything at once when the stream ends.
//
// The class is a tiny external store (subscribe/getSnapshot) so that only the
// component rendering the live message re-renders per frame, never the chat.

// Steady reveal speed with an empty backlog, in characters per second.
const BASE_CHARS_PER_SEC = 90;
// Extra speed per buffered character, per second. With a backlog of B chars
// the reveal runs at BASE + B * CATCH_UP chars/sec, so the backlog drains
// with a time constant of 1 / CATCH_UP seconds (about 1/4 s behind).
const CATCH_UP_PER_SEC = 4;
// A frame gap longer than this (background tab, debugger pause) counts as
// this long, so returning to the tab doesn't dump the backlog in one frame.
const MAX_FRAME_MS = 100;

/** How many characters to reveal this frame. `carry` is the fractional
 *  remainder from earlier frames, so slow speeds still average out. */
export function revealStep(backlog: number, dtMs: number, carry: number): { count: number; carry: number } {
  if (backlog <= 0) return { count: 0, carry: 0 };
  const dt = Math.min(Math.max(dtMs, 0), MAX_FRAME_MS) / 1000;
  const exact = carry + (BASE_CHARS_PER_SEC + backlog * CATCH_UP_PER_SEC) * dt;
  const count = Math.min(backlog, Math.floor(exact));
  return { count, carry: count === backlog ? 0 : exact - count };
}

export class SmoothReveal {
  private target = '';
  private shown = 0;
  private carry = 0;
  private raf = 0;
  private lastTime = 0;
  private listeners = new Set<() => void>();

  /** Add newly received text to the buffer. */
  push(text: string): void {
    if (!text) return;
    this.target += text;
    if (!this.raf) {
      this.lastTime = performance.now();
      this.raf = requestAnimationFrame(this.tick);
    }
  }

  /** Show everything received so far, immediately, and stop the loop. */
  flush(): void {
    this.stop();
    if (this.shown !== this.target.length) {
      this.shown = this.target.length;
      this.emit();
    }
  }

  /** Stop the animation loop without revealing more (e.g. on unmount). */
  stop(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.carry = 0;
  }

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  };

  getSnapshot = (): string => this.target.slice(0, this.shown);

  private tick = (now: number): void => {
    const { count, carry } = revealStep(this.target.length - this.shown, now - this.lastTime, this.carry);
    this.lastTime = now;
    this.carry = carry;
    if (count > 0) {
      let next = this.shown + count;
      // Never split a surrogate pair (emoji, some math symbols).
      const code = this.target.charCodeAt(next - 1);
      if (code >= 0xd800 && code <= 0xdbff && next < this.target.length) next += 1;
      this.shown = next;
      this.emit();
    }
    this.raf = this.shown < this.target.length ? requestAnimationFrame(this.tick) : 0;
  };

  private emit(): void {
    for (const l of this.listeners) l();
  }
}

// ==================== Partial Markdown/math handling ====================

/**
 * Scans streamed Markdown the way remark-math reads it, closely enough for
 * display. Skips code fences, inline code spans, and backslash escapes.
 *
 * - `openMathAt`: index of the `$` or `$$` that opens a math span still
 *   unclosed at the end of the text, or -1 when there isn't one.
 * - `blockStarts`: indexes where a new top-level block starts after a blank
 *   line, outside code fences and display math. The live view uses these to
 *   memoize finished blocks, so each frame only re-parses the last one.
 */
export function scanStreamingMarkdown(text: string): { openMathAt: number; blockStarts: number[] } {
  const blockStarts: number[] = [];
  let fence: string | null = null;   // open ``` or ~~~ fence marker
  let codeTicks = 0;                 // backtick run length of an open code span
  let math: '$' | '$$' | null = null;
  let mathAt = -1;
  let i = 0;
  let lineStart = true;

  while (i < text.length) {
    if (lineStart) {
      lineStart = false;
      const eol = text.indexOf('\n', i);
      const line = text.slice(i, eol === -1 ? text.length : eol);
      const fenceMatch = /^ {0,3}(`{3,}|~{3,})/.exec(line);
      if (fenceMatch && !math && !codeTicks) {
        const marker = fenceMatch[1];
        if (fence === null) fence = marker;
        else if (marker[0] === fence[0] && marker.length >= fence.length && line.trim() === marker) fence = null;
        if (eol === -1) break;
        i = eol + 1;
        lineStart = true;
        continue;
      }
      if (fence !== null) {
        if (eol === -1) break;
        i = eol + 1;
        lineStart = true;
        continue;
      }
      if (line.trim() === '' && eol !== -1) {
        // Blank line: ends a paragraph, so an inline $ or code span left open
        // in it can never close (remark-math wouldn't pair across it either).
        if (math === '$') { math = null; mathAt = -1; }
        codeTicks = 0;
        if (math === null) {
          let next = eol + 1;
          while (next < text.length && text[next] === '\n') next += 1;
          if (next < text.length && text.slice(next).trim() !== '') blockStarts.push(next);
        }
        i = eol + 1;
        lineStart = true;
        continue;
      }
    }

    const ch = text[i];
    if (ch === '\n') { i += 1; lineStart = true; continue; }
    if (ch === '\\' && !codeTicks) { i += 2; continue; }
    if (ch === '`' && !math) {
      let run = 1;
      while (text[i + run] === '`') run += 1;
      if (!codeTicks) codeTicks = run;
      else if (run === codeTicks) codeTicks = 0;
      i += run;
      continue;
    }
    if (ch === '$' && !codeTicks) {
      const delim = text[i + 1] === '$' ? '$$' : '$';
      if (math === null) { math = delim; mathAt = i; }
      else if (math === delim) { math = null; mathAt = -1; }
      i += delim.length;
      continue;
    }
    i += 1;
  }

  return { openMathAt: math ? mathAt : -1, blockStarts };
}

/** Backslash-escape every ASCII punctuation character, so CommonMark renders
 *  the text literally (and remark-math sees no `$` delimiters). */
function escapeMarkdown(text: string): string {
  return text.replace(/[!-/:-@[-`{-~]/g, '\\$&');
}

/**
 * Splits live streamed Markdown into blocks ready to render. Earlier blocks
 * are finished, so they can be memoized. In the last block, a math span that
 * hasn't closed yet is escaped to plain text until its closing delimiter
 * arrives, so KaTeX never renders half an expression.
 */
export function prepareStreamingBlocks(text: string): string[] {
  const { openMathAt, blockStarts } = scanStreamingMarkdown(text);
  const bounds = [0, ...blockStarts, text.length];
  const blocks: string[] = [];
  for (let b = 0; b < bounds.length - 1; b++) {
    const start = bounds[b];
    const end = bounds[b + 1];
    if (openMathAt >= start && openMathAt < end) {
      blocks.push(text.slice(start, openMathAt) + escapeMarkdown(text.slice(openMathAt, end)));
    } else {
      blocks.push(text.slice(start, end));
    }
  }
  return blocks;
}
