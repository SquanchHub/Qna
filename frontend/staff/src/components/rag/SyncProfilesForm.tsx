import { useState } from 'react';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import type { Profile } from '../../lib/ragTypes';
import { Button } from '../ui/button';

interface SyncProfilesFormProps {
  profiles: Profile[];
  busy: boolean;
  /** `undefined` means every profile, sent as `{}` (an empty list is a 422). */
  onSync: (profileIds: number[] | undefined) => void;
  onCancel?: () => void;
  submitLabel?: string;
}

/** Profile checkboxes for a resource sync, all ticked by default. */
export function SyncProfilesForm({
  profiles,
  busy,
  onSync,
  onCancel,
  submitLabel = 'Sync',
}: SyncProfilesFormProps) {
  const [selected, setSelected] = useState<Set<number>>(() => new Set(profiles.map((p) => p.id)));

  if (profiles.length === 0) {
    return (
      <p className="text-sm text-slate-400">
        No ingestion profiles yet.{' '}
        <Link to="/profiles" className="text-indigo-400 hover:text-indigo-300">
          Create one on the Profiles page
        </Link>{' '}
        before syncing.
      </p>
    );
  }

  function toggle(id: number) {
    setSelected((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function submit() {
    const all = profiles.every((p) => selected.has(p.id));
    onSync(all ? undefined : profiles.filter((p) => selected.has(p.id)).map((p) => p.id));
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      {profiles.map((p) => (
        <label key={p.id} className="flex items-center gap-1.5 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={selected.has(p.id)}
            onChange={() => toggle(p.id)}
            className="accent-indigo-500"
          />
          {p.name}
        </label>
      ))}
      <Button size="sm" onClick={submit} disabled={busy || selected.size === 0}>
        <span className="flex items-center gap-1.5">
          <RefreshCw size={14} /> {busy ? 'Starting…' : submitLabel}
        </span>
      </Button>
      {onCancel && (
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      )}
    </div>
  );
}
