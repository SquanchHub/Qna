import { Fragment, useEffect, useState } from 'react';
import { Link2, RefreshCw, Trash2, Upload } from 'lucide-react';
import { api, errorMessage } from '../lib/api';
import { useCourse } from '../lib/CourseContext';
import {
  ragPaths,
  type CreatableResourceType,
  type CreateResourceRequest,
  type Job,
  type Profile,
  type Resource,
  type SyncResourceRequest,
  type SyncResourceResponse,
} from '../lib/ragTypes';
import { formatTimestamp } from '../lib/utils';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Select } from '../components/ui/select';
import { StatusBadge, isActive } from '../components/rag/StatusBadge';
import { SyncProfilesForm } from '../components/rag/SyncProfilesForm';

const POLL_MS = 3000;

const TYPE_LABELS: Record<Resource['resource_type'], string> = {
  syllabus: 'Syllabus',
  schedule: 'Schedule',
  repository: 'Repository',
  historical_qa: 'Historical Q&A',
};

// TODO(design §6): confirm with backend — which extensions each type accepts on upload
// (§4.5.1 table); the server's UNSUPPORTED_FILE is the real check.
const UPLOAD_ACCEPT: Record<CreatableResourceType, string> = {
  syllabus: '.html',
  schedule: '.html',
  repository: '.zip,.md,.pdf',
};

// TODO(design §6): confirm with backend — MAX_UPLOAD_MB / MAX_ZIP_MB are env settings the
// frontend can't read; these are the §4.3.2 initial values. The server's 413 is authoritative.
const MAX_UPLOAD_MB = 20;
const MAX_ZIP_MB = 50;

export default function ResourcesPage() {
  const { courseId } = useCourse();
  const [resources, setResources] = useState<Resource[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState(false);

  // Register by URL
  const [urlType, setUrlType] = useState<CreatableResourceType>('syllabus');
  const [urlTitle, setUrlTitle] = useState('');
  const [url, setUrl] = useState('');
  const [gitRef, setGitRef] = useState('');
  const [subpath, setSubpath] = useState('');
  const [urlError, setUrlError] = useState('');
  const [registering, setRegistering] = useState(false);

  // Upload fallback
  const [uploadType, setUploadType] = useState<CreatableResourceType>('repository');
  const [uploadTitle, setUploadTitle] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [citationBase, setCitationBase] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploadError, setUploadError] = useState('');
  const [uploading, setUploading] = useState(false);

  // The resource just registered or uploaded, offered an inline "Sync now".
  const [created, setCreated] = useState<Resource | null>(null);
  // The resource whose Re-sync picker is open.
  const [resyncId, setResyncId] = useState<number | null>(null);

  async function load() {
    if (!courseId) return;
    try {
      const [r, p, j] = await Promise.all([
        api.get<Resource[]>(ragPaths.resources(courseId)),
        api.get<Profile[]>(ragPaths.profiles(courseId)),
        api.get<Job[]>(ragPaths.jobs(courseId)),
      ]);
      setResources(r);
      setProfiles(p);
      setJobs(j);
      setLoadError('');
    } catch (err) {
      setLoadError(errorMessage(err, 'Failed to load resources'));
    }
  }

  useEffect(() => {
    setCreated(null);
    setResyncId(null);
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courseId]);

  const anyActive =
    jobs.some((j) => isActive(j.status)) ||
    profiles.some((p) => p.active_job_id !== null) ||
    resources.some((r) => r.states.some((s) => isActive(s.status)));

  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyActive, courseId]);

  async function handleRegister(e: React.FormEvent) {
    e.preventDefault();
    if (!courseId) return;
    setRegistering(true);
    setUrlError('');
    const body: CreateResourceRequest = { resource_type: urlType, title: urlTitle, url };
    if (urlType === 'repository') {
      if (gitRef.trim()) body.git_ref = gitRef.trim();
      if (subpath.trim()) body.subpath = subpath.trim();
    }
    try {
      const resource = await api.post<Resource>(ragPaths.resources(courseId), body);
      setUrlTitle('');
      setUrl('');
      setGitRef('');
      setSubpath('');
      setCreated(resource);
      await load();
    } catch (err) {
      setUrlError(errorMessage(err, 'Failed to register resource'));
    } finally {
      setRegistering(false);
    }
  }

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!courseId || !file) return;
    const isZip = file.name.toLowerCase().endsWith('.zip');
    const limitMb = isZip ? MAX_ZIP_MB : MAX_UPLOAD_MB;
    if (file.size > limitMb * 1024 * 1024) {
      setUploadError(`File is larger than ${limitMb} MB`);
      return;
    }
    setUploading(true);
    setUploadError('');
    const form = new FormData();
    form.append('resource_type', uploadType);
    form.append('title', uploadTitle);
    form.append('file', file);
    if (citationBase.trim()) form.append('citation_base_url', citationBase.trim());
    try {
      const resource = await api.upload<Resource>(ragPaths.resourceUpload(courseId), form);
      setUploadTitle('');
      setFile(null);
      setCitationBase('');
      setFileInputKey((k) => k + 1);
      setCreated(resource);
      await load();
    } catch (err) {
      setUploadError(errorMessage(err, 'Failed to upload resource'));
    } finally {
      setUploading(false);
    }
  }

  async function handleSync(resourceId: number, profileIds: number[] | undefined) {
    if (!courseId) return;
    setBusy(true);
    setActionError('');
    const body: SyncResourceRequest = profileIds ? { profile_ids: profileIds } : {};
    try {
      await api.post<SyncResourceResponse>(ragPaths.resourceSync(courseId, resourceId), body);
      setResyncId(null);
      if (created?.id === resourceId) setCreated(null);
      await load();
    } catch (err) {
      setActionError(errorMessage(err, 'Failed to start sync'));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(resource: Resource) {
    if (!courseId) return;
    if (!window.confirm(`Delete "${resource.title}" and its chunks in every profile?`)) return;
    setBusy(true);
    setActionError('');
    try {
      await api.delete(ragPaths.resource(courseId, resource.id));
      if (created?.id === resource.id) setCreated(null);
      await load();
    } catch (err) {
      setActionError(errorMessage(err, 'Failed to delete resource'));
    } finally {
      setBusy(false);
    }
  }

  const resourceTitle = (id: number | null) =>
    id === null ? 'All resources' : (resources.find((r) => r.id === id)?.title ?? `Resource #${id}`);

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <h2 className="text-2xl font-bold text-slate-100 mb-6">Resources</h2>
      {loadError && <p className="text-red-400 text-sm mb-4">{loadError}</p>}

      <div className="grid gap-6 md:grid-cols-2 mb-6">
        <Card>
          <CardHeader>
            <h3 className="text-lg font-semibold text-slate-100">Register URL</h3>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleRegister} className="space-y-3">
              <Select
                value={urlType}
                onChange={(e) => setUrlType(e.target.value as CreatableResourceType)}
                className="w-full"
              >
                <option value="syllabus">Syllabus</option>
                <option value="schedule">Schedule</option>
                <option value="repository">Repository</option>
              </Select>
              <Input
                placeholder="Title"
                value={urlTitle}
                onChange={(e) => setUrlTitle(e.target.value)}
                required
              />
              <Input
                type="url"
                placeholder={
                  urlType === 'repository' ? 'https://git.example.edu/group/repo' : 'https://…'
                }
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                required
              />
              {urlType === 'repository' && (
                <>
                  <Input
                    placeholder="Branch or tag (optional, not a commit SHA)"
                    value={gitRef}
                    onChange={(e) => setGitRef(e.target.value)}
                  />
                  <Input
                    placeholder="Subpath within the repo (optional)"
                    value={subpath}
                    onChange={(e) => setSubpath(e.target.value)}
                  />
                </>
              )}
              {urlError && <p className="text-red-400 text-sm">{urlError}</p>}
              <Button type="submit" disabled={registering}>
                <span className="flex items-center gap-1.5">
                  <Link2 size={16} /> {registering ? 'Registering…' : 'Register'}
                </span>
              </Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <h3 className="text-lg font-semibold text-slate-100">Upload file</h3>
            <p className="text-slate-400 text-sm">Fallback when the URL can't be fetched.</p>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleUpload} className="space-y-3">
              <Select
                value={uploadType}
                onChange={(e) => {
                  setUploadType(e.target.value as CreatableResourceType);
                  setFile(null);
                  setFileInputKey((k) => k + 1);
                }}
                className="w-full"
              >
                <option value="syllabus">Syllabus (.html)</option>
                <option value="schedule">Schedule (.html)</option>
                <option value="repository">Repository (.zip, .md or .pdf)</option>
              </Select>
              <Input
                placeholder="Title"
                value={uploadTitle}
                onChange={(e) => setUploadTitle(e.target.value)}
                required
              />
              <Input
                key={fileInputKey}
                type="file"
                accept={UPLOAD_ACCEPT[uploadType]}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                required
              />
              <div>
                <Input
                  type="url"
                  placeholder="Citation base URL (optional)"
                  value={citationBase}
                  onChange={(e) => setCitationBase(e.target.value)}
                />
                {/* TODO(design §6): confirm with backend — how the base joins a single-file
                    upload's name, whether a trailing "/" is needed, and whether it applies to
                    .html uploads. Help text only; no client-side validation. */}
                <p className="text-slate-400 text-xs mt-1">
                  Where students can view this content. For a zip, each file's path inside the
                  zip is appended. Without it, citations show as unlinked text.
                </p>
              </div>
              {uploadError && <p className="text-red-400 text-sm">{uploadError}</p>}
              <Button type="submit" disabled={uploading || !file}>
                <span className="flex items-center gap-1.5">
                  <Upload size={16} /> {uploading ? 'Uploading…' : 'Upload'}
                </span>
              </Button>
            </form>
          </CardContent>
        </Card>
      </div>

      {created && (
        <Card className="mb-6 px-6 py-4 space-y-2">
          <p className="text-slate-100">
            <span className="font-semibold">{created.title}</span> was added but hasn't been
            synced yet.
          </p>
          <SyncProfilesForm
            profiles={profiles}
            busy={busy}
            onSync={(ids) => void handleSync(created.id, ids)}
            onCancel={() => setCreated(null)}
            submitLabel="Sync now"
          />
        </Card>
      )}

      {actionError && <p className="text-red-400 text-sm mb-4">{actionError}</p>}

      <Card className="mb-6 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700 text-left text-slate-400">
              <th className="px-4 py-3 font-medium">Type</th>
              <th className="px-4 py-3 font-medium">Resource</th>
              <th className="px-4 py-3 font-medium">Profiles</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody>
            {resources.map((r) => (
              <Fragment key={r.id}>
                <tr className="border-b border-slate-700/60 align-top">
                  <td className="px-4 py-3">
                    <Badge variant="outline">{TYPE_LABELS[r.resource_type]}</Badge>
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-semibold text-slate-100">{r.title}</p>
                    <ResourceSource resource={r} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap gap-1.5">
                      {r.states.map((s) => (
                        <StatusBadge
                          key={s.profile_id}
                          status={s.status}
                          title={[
                            `Last synced: ${formatTimestamp(s.last_synced_at)}`,
                            s.last_commit_sha && `Commit: ${s.last_commit_sha.slice(0, 8)}`,
                            s.error && `Error: ${s.error}`,
                          ]
                            .filter(Boolean)
                            .join('\n')}
                        >
                          {s.profile_name}: {s.status} · {s.chunk_count}
                        </StatusBadge>
                      ))}
                      {r.states.length === 0 && <span className="text-slate-500">No profiles</span>}
                    </div>
                    {latestSync(r) && (
                      <p className="text-slate-500 text-xs mt-1">
                        Last synced{' '}
                        {formatTimestamp(latestSync(r))}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => setResyncId(resyncId === r.id ? null : r.id)}
                        disabled={busy}
                        title="Re-sync"
                      >
                        <RefreshCw size={14} />
                      </Button>
                      {r.source_kind !== 'internal' && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => void handleDelete(r)}
                          disabled={busy}
                          title="Delete"
                        >
                          <Trash2 size={14} />
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
                {resyncId === r.id && (
                  <tr className="border-b border-slate-700/60">
                    <td colSpan={4} className="px-4 py-3">
                      <SyncProfilesForm
                        profiles={profiles}
                        busy={busy}
                        onSync={(ids) => void handleSync(r.id, ids)}
                        onCancel={() => setResyncId(null)}
                        submitLabel="Re-sync"
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
            {resources.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-6 text-center text-slate-500">
                  No resources yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      <Card>
        <CardHeader>
          <h3 className="text-lg font-semibold text-slate-100">Recent jobs</h3>
        </CardHeader>
        <CardContent className="space-y-2">
          {jobs.map((j) => (
            <div key={j.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <StatusBadge status={j.status} />
              <span className="text-slate-100">
                #{j.id} {j.profile_name}
              </span>
              <span className="text-slate-400">{resourceTitle(j.resource_id)}</span>
              <span className="text-slate-500">
                +{j.chunks_added} ~{j.chunks_updated} −{j.chunks_deleted}
              </span>
              <span className="text-slate-500">
                {formatTimestamp(j.finished_at ?? j.started_at ?? j.created_at)}
              </span>
              {j.error && <span className="w-full text-red-400">{j.error}</span>}
            </div>
          ))}
          {jobs.length === 0 && <p className="text-slate-500 text-sm">No jobs yet.</p>}
        </CardContent>
      </Card>
    </div>
  );
}

/** Most recent sync across profiles; ISO 8601 UTC strings sort chronologically. */
function latestSync(r: Resource): string | null {
  return r.states.reduce<string | null>(
    (latest, s) => (s.last_synced_at && (!latest || s.last_synced_at > latest) ? s.last_synced_at : latest),
    null
  );
}

function ResourceSource({ resource: r }: { resource: Resource }) {
  if (r.source_kind === 'internal') {
    return <p className="text-slate-400 text-xs">Resolved board threads</p>;
  }
  if (r.source_kind === 'upload') {
    return (
      <p className="text-slate-400 text-xs break-all">
        Uploaded: {r.original_filename ?? 'file'}
        {r.citation_base_url && <> · cites {r.citation_base_url}</>}
      </p>
    );
  }
  return (
    <p className="text-slate-400 text-xs break-all">
      {r.url && (
        <a href={r.url} target="_blank" rel="noreferrer" className="hover:text-slate-200">
          {r.url}
        </a>
      )}
      {r.git_ref && <> · ref {r.git_ref}</>}
      {r.subpath && <> · {r.subpath}</>}
    </p>
  );
}
