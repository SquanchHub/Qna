import { useEffect, useState } from 'react';
import { Plus, RefreshCw, Trash2 } from 'lucide-react';
import { api, errorMessage } from '../lib/api';
import { useCourse } from '../lib/CourseContext';
import {
  PROFILE_NAME_PATTERN,
  ragPaths,
  type Chunker,
  type ChunkingConfig,
  type CreateProfileRequest,
  type Job,
  type Preset,
  type Profile,
  type RagHealth,
} from '../lib/ragTypes';
import { formatTimestamp } from '../lib/utils';
import { Badge, type BadgeVariant } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Select } from '../components/ui/select';

const POLL_MS = 3000;

function describeChunker(c: Chunker): string {
  if (c.method === 'semantic') {
    return `semantic ${c.similarity_threshold}, cap ${c.max_tokens}`;
  }
  const reset = c.reset_at && c.reset_at !== 'none' ? `, reset at ${c.reset_at}` : '';
  return `window ${c.chunk_size}/${c.chunk_overlap}${reset}`;
}

function describeChunking(chunking: ChunkingConfig): string {
  // Guarded: the §6 example shows `chunking: {}`.
  if (!chunking?.default) return '—';
  const parts = [`default ${describeChunker(chunking.default)}`];
  for (const [type, c] of Object.entries(chunking.per_type ?? {})) {
    if (c) parts.push(`${type} ${describeChunker(c)}`);
  }
  return parts.join(' · ');
}

export default function ProfilesPage() {
  const { courseId } = useCourse();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [health, setHealth] = useState<RagHealth | null>(null);
  const [healthError, setHealthError] = useState('');
  const [preset, setPreset] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [actionError, setActionError] = useState('');
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(false);

  async function load() {
    if (!courseId) return;
    try {
      setProfiles(await api.get<Profile[]>(ragPaths.profiles(courseId)));
    } catch (err) {
      setActionError(errorMessage(err, 'Failed to load profiles'));
    }
  }

  async function loadHealth() {
    try {
      setHealth(await api.get<RagHealth>(ragPaths.health));
      setHealthError('');
    } catch (err) {
      setHealth(null);
      setHealthError(errorMessage(err, 'Failed to load health'));
    }
  }

  useEffect(() => {
    if (!courseId) return;
    void load();
    api
      .get<Preset[]>(ragPaths.presets(courseId))
      .then((data) => {
        setPresets(data);
        setPreset((current) => current || (data[0]?.preset ?? ''));
      })
      .catch((err) => setError(errorMessage(err, 'Failed to load presets')));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  useEffect(() => {
    void loadHealth();
  }, []);

  const anyActive = profiles.some((p) => p.active_job_id !== null);

  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyActive, courseId]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!courseId || !preset) return;
    const trimmed = name.trim();
    if (trimmed && !PROFILE_NAME_PATTERN.test(trimmed)) {
      setError(
        'Name must be 3–64 lowercase letters, digits or hyphens, and start and end with a letter or digit'
      );
      return;
    }
    setSaving(true);
    setError('');
    const body: CreateProfileRequest = trimmed ? { preset, name: trimmed } : { preset };
    try {
      await api.post<Profile>(ragPaths.profiles(courseId), body);
      setName('');
      await load();
    } catch (err) {
      setError(errorMessage(err, 'Failed to create profile'));
    } finally {
      setSaving(false);
    }
  }

  async function handleSyncAll(profileId: number) {
    if (!courseId) return;
    setBusy(true);
    setActionError('');
    try {
      await api.post<Job>(ragPaths.profileSync(courseId, profileId), {});
      await load();
    } catch (err) {
      setActionError(errorMessage(err, 'Failed to start sync'));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(profile: Profile) {
    if (!courseId) return;
    if (!window.confirm(`Delete profile "${profile.name}" and its collection?`)) return;
    setBusy(true);
    setActionError('');
    try {
      await api.delete(ragPaths.profile(courseId, profile.id));
      await load();
    } catch (err) {
      setActionError(errorMessage(err, 'Failed to delete profile'));
    } finally {
      setBusy(false);
    }
  }

  const selectedPreset = presets.find((p) => p.preset === preset);

  return (
    <div className="p-8 max-w-3xl mx-auto">
      <h2 className="text-2xl font-bold text-slate-100 mb-6">Ingestion Profiles</h2>

      <Card className="mb-6">
        <CardHeader>
          <h3 className="text-lg font-semibold text-slate-100">Create from preset</h3>
          <p className="text-slate-400 text-sm">
            Profiles never change. To try another configuration, create another profile.
          </p>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleCreate} className="space-y-3">
            <Select value={preset} onChange={(e) => setPreset(e.target.value)} className="w-full">
              {presets.map((p) => (
                <option key={p.preset} value={p.preset}>
                  {p.preset} — {p.embedding_model}
                </option>
              ))}
            </Select>
            {selectedPreset && (
              <p className="text-slate-400 text-xs">{describeChunking(selectedPreset.chunking)}</p>
            )}
            <Input
              placeholder={preset ? `Name (defaults to ${preset})` : 'Name (optional)'}
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <Button type="submit" disabled={saving || !preset}>
              <span className="flex items-center gap-1.5">
                <Plus size={16} /> {saving ? 'Creating…' : 'Create'}
              </span>
            </Button>
          </form>
        </CardContent>
      </Card>

      {actionError && <p className="text-red-400 text-sm mb-4">{actionError}</p>}

      <div className="space-y-3 mb-6">
        {profiles.map((p) => (
          <Card key={p.id} className="px-6 py-4 flex items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <p className="flex items-center gap-2 font-semibold text-slate-100">
                {p.name}
                {p.name !== p.preset && <Badge variant="outline">{p.preset}</Badge>}
                {p.active_job_id !== null && <Badge variant="info">Syncing</Badge>}
              </p>
              <p className="text-slate-400 text-sm break-all">{p.embedding_model}</p>
              <p className="text-slate-400 text-sm">
                {p.chunk_count} chunks · {p.collection_name} · created {formatTimestamp(p.created_at)}
              </p>
              <p className="text-slate-500 text-xs">{describeChunking(p.chunking)}</p>
            </div>
            <div className="flex shrink-0 gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleSyncAll(p.id)}
                disabled={busy || p.active_job_id !== null}
                title="Sync all resources"
              >
                <span className="flex items-center gap-1.5">
                  <RefreshCw size={14} /> Sync all
                </span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => void handleDelete(p)}
                disabled={busy}
                title="Delete"
              >
                <Trash2 size={14} />
              </Button>
            </div>
          </Card>
        ))}
        {profiles.length === 0 && <p className="text-slate-500 text-sm">No profiles yet.</p>}
      </div>

      <Card>
        <CardHeader className="flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-100">Service health</h3>
          <Button variant="ghost" size="sm" onClick={() => void loadHealth()}>
            <RefreshCw size={14} />
          </Button>
        </CardHeader>
        <CardContent>
          {healthError && <p className="text-red-400 text-sm">{healthError}</p>}
          {health && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <HealthRow label="Ollama" ok={health.ollama.ok} detail={health.ollama.models.join(', ')} />
              <HealthRow
                label="Infinity"
                ok={health.infinity.ok}
                detail={health.infinity.models.join(', ')}
              />
              <HealthRow
                label="Chroma"
                ok={health.chroma.ok}
                detail={`server ${health.chroma.server_version ?? '?'}, client ${health.chroma.client_version}`}
              />
              <HealthRow
                label="GitLab token"
                ok={health.gitlab_token_configured}
                okText="configured"
                downText="missing"
              />
              <HealthRow
                label="Live answering"
                ok={health.live_enabled}
                okText="on"
                downText="off"
                downVariant="outline"
              />
              <dt className="text-slate-400">Defaults</dt>
              <dd className="text-slate-300 break-all">
                {health.defaults.profile} · threshold {health.defaults.threshold} ·{' '}
                {health.defaults.model}
              </dd>
            </dl>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function HealthRow({
  label,
  ok,
  detail,
  okText = 'ok',
  downText = 'down',
  downVariant = 'danger',
}: {
  label: string;
  ok: boolean;
  detail?: string;
  okText?: string;
  downText?: string;
  /** Off isn't always a fault (live answering is off during harness runs). */
  downVariant?: BadgeVariant;
}) {
  return (
    <>
      <dt className="text-slate-400">{label}</dt>
      <dd className="flex flex-wrap items-center gap-2 text-slate-300">
        <Badge variant={ok ? 'success' : downVariant}>{ok ? okText : downText}</Badge>
        {detail && <span className="break-all">{detail}</span>}
      </dd>
    </>
  );
}
