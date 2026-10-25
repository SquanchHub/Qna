// API types for the RAG ingestion routes. These mirror docs/design-rag.md
// §6 (and the §4.4.1 chunking shape) field for field: when the backend
// contract changes, update the design doc first, then this file.

// ---- Enums (§5, §6) ----

export type ResourceType = 'syllabus' | 'schedule' | 'repository' | 'historical_qa';

/** Types staff can register or upload; historical_qa is system-created. */
export type CreatableResourceType = Exclude<ResourceType, 'historical_qa'>;

export type SourceKind = 'url' | 'upload' | 'internal';

/** `NEVER` is synthesized by the API for a profile with no state row. */
export type ResourceStateStatus = 'NEVER' | 'QUEUED' | 'RUNNING' | 'READY' | 'FAILED';

export type JobStatus = 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED';

export type JobScope = 'resource' | 'profile';

// ---- Chunking config (§4.4.1) ----

/** `per_type` keys are chunk types, not resource types. */
export type ChunkingType = 'syllabus' | 'schedule' | 'repo_markdown' | 'repo_pdf';

export type ResetAt = 'none' | 'page' | 'subheading';

export interface WindowSize {
  chunk_size: number;
  chunk_overlap: number;
}

export interface SlidingWindowChunker extends WindowSize {
  method: 'sliding_window';
  reset_at?: ResetAt;
}

/** Allowed only for syllabus and schedule. */
export interface SemanticChunker {
  method: 'semantic';
  similarity_threshold: number;
  max_tokens: number;
  oversize_window: WindowSize;
}

export type Chunker = SlidingWindowChunker | SemanticChunker;

export interface ChunkingConfig {
  token_unit: 'minilm-wordpiece';
  heading_prefix_max_tokens: number;
  default: SlidingWindowChunker;
  per_type?: Partial<Record<ChunkingType, Chunker>>;
}

// ---- Response shapes (§6) ----

export interface Preset {
  preset: string;
  embedding_model: string;
  // TODO(design §6): confirm with backend — "" vs null when a preset has no instruction.
  query_instruction: string | null;
  chunking: ChunkingConfig;
}

export interface Profile {
  id: number;
  course_id: number;
  name: string;
  preset: string;
  embedding_model: string;
  // TODO(design §6): confirm with backend — §6 example shows "", §5 column is plain TEXT.
  query_instruction: string | null;
  // TODO(design §6): confirm with backend — §6 example shows `{}`; typed as the §4.4.1 shape.
  chunking: ChunkingConfig;
  /** Display only; refreshed at job finish and resource delete. */
  chunk_count: number;
  collection_name: string;
  /** The profile's QUEUED/RUNNING job, at most one. */
  active_job_id: number | null;
  created_at: string;
}

export interface ResourceState {
  profile_id: number;
  profile_name: string;
  status: ResourceStateStatus;
  chunk_count: number;
  last_commit_sha: string | null;
  last_synced_at: string | null;
  error: string | null;
}

export interface Resource {
  id: number;
  course_id: number;
  resource_type: ResourceType;
  source_kind: SourceKind;
  title: string;
  url: string | null;
  git_ref: string | null;
  subpath: string | null;
  citation_base_url: string | null;
  original_filename: string | null;
  created_at: string;
  /** One entry per course profile. */
  states: ResourceState[];
}

export interface Job {
  id: number;
  course_id: number;
  profile_id: number;
  profile_name: string;
  scope: JobScope;
  /** Set exactly when scope is 'resource'. */
  resource_id: number | null;
  status: JobStatus;
  chunks_added: number;
  chunks_updated: number;
  chunks_deleted: number;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface SyncResourceResponse {
  jobs: Job[];
}

// TODO(design §6): confirm with backend — §6 lists only key names for health; element
// and null types here are assumed.
export interface ServiceHealth {
  ok: boolean;
  models: string[];
}

export interface RagHealth {
  ollama: ServiceHealth;
  infinity: ServiceHealth;
  chroma: { ok: boolean; server_version: string | null; client_version: string };
  gitlab_token_configured: boolean;
  live_enabled: boolean;
  defaults: { profile: string; threshold: number; model: string };
}

// ---- Request shapes (§6) ----

export interface CreateProfileRequest {
  preset: string;
  /** Defaults to `preset` when omitted. */
  name?: string;
}

export interface CreateResourceRequest {
  resource_type: CreatableResourceType;
  title: string;
  url: string;
  /** Repository only; branch or tag name, not a SHA. */
  git_ref?: string;
  /** Repository only; relative, no `..`. */
  subpath?: string;
}

/** Omit `profile_ids` for "all"; an empty list is a 422. */
export interface SyncResourceRequest {
  profile_ids?: number[];
}

/** Multipart fields for POST /rag/resources/upload. */
export interface UploadResourceFields {
  resource_type: CreatableResourceType;
  title: string;
  file: File;
  citation_base_url?: string;
}

// ---- Errors (§6) ----

export type RagErrorCode =
  | 'VALIDATION_ERROR'
  | 'UNKNOWN_PRESET'
  | 'EMBEDDING_MODEL_NOT_SERVED'
  | 'DUPLICATE_PROFILE'
  | 'PROFILE_NOT_FOUND'
  | 'RESOURCE_NOT_FOUND'
  | 'JOB_NOT_FOUND'
  | 'JOB_RUNNING'
  | 'NO_PROFILES'
  | 'URL_NOT_ALLOWED'
  | 'PAYLOAD_TOO_LARGE'
  | 'UNSUPPORTED_FILE'
  | 'UNSAFE_ARCHIVE'
  | 'PROTECTED_RESOURCE';

/** Profile names: lowercase alphanumerics and hyphens, 3–64 chars (§5). */
export const PROFILE_NAME_PATTERN = /^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/;

// ---- Paths (§6), relative to /api ----

export const ragPaths = {
  health: '/rag/health',
  presets: (courseId: number) => `/courses/${courseId}/rag/presets`,
  profiles: (courseId: number) => `/courses/${courseId}/rag/profiles`,
  profile: (courseId: number, profileId: number) => `/courses/${courseId}/rag/profiles/${profileId}`,
  profileSync: (courseId: number, profileId: number) =>
    `/courses/${courseId}/rag/profiles/${profileId}/sync`,
  resources: (courseId: number) => `/courses/${courseId}/rag/resources`,
  resourceUpload: (courseId: number) => `/courses/${courseId}/rag/resources/upload`,
  resource: (courseId: number, resourceId: number) =>
    `/courses/${courseId}/rag/resources/${resourceId}`,
  resourceSync: (courseId: number, resourceId: number) =>
    `/courses/${courseId}/rag/resources/${resourceId}/sync`,
  // TODO(design §6): confirm with backend — whether `status=` takes one value or a list;
  // the UI filters client-side and never sends it.
  jobs: (courseId: number, limit = 20) => `/courses/${courseId}/rag/jobs?limit=${limit}`,
  job: (courseId: number, jobId: number) => `/courses/${courseId}/rag/jobs/${jobId}`,
};
