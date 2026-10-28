import { ExternalLink, Sparkles } from 'lucide-react';
import type { AiStatus, Citation } from '../lib/types';
import { citationLabel, isLinkable } from '../lib/citations';
import { Badge } from './ui/badge';

export function AiBadge() {
  return (
    <Badge variant="ai" className="gap-1">
      <Sparkles size={12} /> AI-generated
    </Badge>
  );
}

export function AiDisclaimer() {
  return (
    <p className="text-xs text-muted mt-3">
      Generated automatically from course materials. Not reviewed by staff unless marked Verified.
    </p>
  );
}

export function CitationList({ citations }: { citations: Citation[] }) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-4 border-t border-border pt-3">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted mb-1.5">Sources</p>
      <ol className="space-y-1 text-sm">
        {[...citations]
          .sort((a, b) => a.rank - b.rank)
          .map((c) => {
            const { label, detail } = citationLabel(c);
            return (
              <li key={c.rank} className="flex gap-2">
                <span className="text-muted tabular-nums">[{c.rank}]</span>
                <span className="min-w-0 break-words">
                  {isLinkable(c.source_url) ? (
                    <a
                      href={c.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-accent hover:underline"
                    >
                      {label}
                      <ExternalLink size={12} className="inline ml-1 align-baseline" />
                    </a>
                  ) : (
                    <span className="text-secondary">{label}</span>
                  )}
                  {detail && detail !== label && (
                    <span className="text-muted"> · {detail}</span>
                  )}
                </span>
              </li>
            );
          })}
      </ol>
    </div>
  );
}

const STATUS_TEXT: Partial<Record<AiStatus, string>> = {
  PENDING: 'AI assistant is looking for an answer…',
  ANSWERED: 'AI assistant answered',
  NO_MATCH: 'No confident AI answer',
  DECLINED: 'No confident AI answer',
  SKIPPED: 'AI assistant skipped this question',
  FAILED: 'AI assistant could not answer',
};

/** One muted line; nothing for NONE (no attempt was made). */
export function AiStatusNote({ status }: { status: AiStatus }) {
  const text = STATUS_TEXT[status];
  if (!text) return null;
  return (
    <span className="inline-flex items-center gap-1 text-xs text-muted">
      <Sparkles size={12} className={status === 'PENDING' ? 'animate-pulse' : ''} /> {text}
    </span>
  );
}
