import type { Citation, Post } from './types';

/** Citation URLs are built at ingestion (design-rag.md §4.1.1); the post only
 *  stores the URL and a title, so the file, line range, page and quoted
 *  passage are read back out of `source_url`. */

const WEB_TYPE_NAMES: Record<string, string> = {
  syllabus: 'Syllabus',
  schedule: 'Schedule',
};

export function isLinkable(url: string): boolean {
  return /^https?:\/\//i.test(url);
}

function decode(s: string): string {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
}

/** Repo-relative path from a GitLab blob/raw permalink or an upload:// ref,
 *  else the URL's last path segment. */
function filePath(url: string): string | null {
  const m =
    url.match(/\/-\/(?:blob|raw)\/[^/]+\/([^?#]+)/) ?? url.match(/^upload:\/\/[^/]+\/([^?#]+)/);
  if (m) return decode(m[1]);
  const last = url.split(/[?#]/)[0].split('/').filter(Boolean).pop();
  return last ? decode(last) : null;
}

function lineRange(url: string): string | null {
  const m = url.match(/#L(\d+)(?:-(\d+))?$/);
  if (!m) return null;
  return m[2] && m[2] !== m[1] ? `lines ${m[1]}–${m[2]}` : `line ${m[1]}`;
}

function pageNumber(url: string): string | null {
  const m = url.match(/#page=(\d+)/);
  return m ? `page ${m[1]}` : null;
}

/** `#:~:text=start,end` → "start … end". */
function passage(url: string): string | null {
  const m = url.match(/#:~:text=(.+)$/);
  if (!m) return null;
  return m[1].split(',').map(decode).join(' … ');
}

/** Link text for a citation, plus a secondary detail when the title adds
 *  something the link text doesn't. */
export function citationLabel(c: Citation): { label: string; detail: string | null } {
  const url = c.source_url;
  switch (c.resource_type) {
    case 'historical_qa':
      return { label: `Past thread: ${c.title}`, detail: null };
    case 'repo_markdown': {
      const file = filePath(url) ?? c.title;
      const lines = lineRange(url);
      return { label: lines ? `${file}, ${lines}` : file, detail: c.title };
    }
    case 'repo_pdf': {
      const file = filePath(url) ?? c.title;
      const page = pageNumber(url);
      return { label: page ? `${file}, ${page}` : file, detail: null };
    }
    default: {
      const kind = WEB_TYPE_NAMES[c.resource_type] ?? 'Web page';
      const quote = passage(url);
      return quote
        ? { label: `${kind} passage: “${quote}”`, detail: c.title }
        : { label: `${kind}: ${c.title}`, detail: null };
    }
  }
}

/** The AI body ends with a plain-text "Sources:" block (§4.1.3) for places
 *  that can't render citations; drop it where the list is rendered instead. */
export function aiAnswerText(post: Post): string {
  if (!post.citations?.length) return post.body;
  const i = post.body.lastIndexOf('\n\nSources:\n');
  return i === -1 ? post.body : post.body.slice(0, i);
}
