export interface MyCourse {
  id: number;
  name: string;
  semester: string;
  role: 'STUDENT' | 'STAFF';
}

export interface Category {
  id: number;
  course_id: number;
  name: string;
  description: string;
  created_at: string;
}

export interface AuthorSummary {
  id: string;
  display_name: string;
}

export interface QuestionSummary {
  id: number;
  course_id: number;
  title: string;
  status: 'OPEN' | 'CLOSED';
  author: AuthorSummary;
  categories: Category[];
  post_count: number;
  has_accepted_answer: boolean;
  ai_status: AiStatus;
  created_at: string;
  updated_at: string;
}

/** What the auto-responder did for a question (design-rag.md §4.2.3). */
export type AiStatus =
  | 'NONE'
  | 'PENDING'
  | 'ANSWERED'
  | 'NO_MATCH'
  | 'DECLINED'
  | 'SKIPPED'
  | 'FAILED';

/** Chunk types a citation can come from (design-rag.md §4.1.1). */
export type CitationResourceType =
  | 'syllabus'
  | 'schedule'
  | 'repo_markdown'
  | 'repo_pdf'
  | 'historical_qa';

/** One source on an AI post, rank-ordered (design-rag.md §4.1.3). */
export interface Citation {
  rank: number;
  resource_type: CitationResourceType;
  title: string;
  source_url: string;
  similarity_score: number;
}

export interface Post {
  id: number;
  question_id: number;
  author: AuthorSummary;
  author_role: 'STUDENT' | 'STAFF' | 'AI';
  kind: 'ANSWER' | 'FOLLOWUP';
  body: string;
  is_accepted: boolean;
  accepted_by: AuthorSummary | null;
  accepted_at: string | null;
  /** AI posts only; null on human posts. */
  citations: Citation[] | null;
  ai_model: string | null;
  created_at: string;
}

export interface QuestionDetail {
  id: number;
  course_id: number;
  title: string;
  body: string;
  status: 'OPEN' | 'CLOSED';
  author: AuthorSummary;
  categories: Category[];
  posts: Post[];
  ai_status: AiStatus;
  closed_by: AuthorSummary | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}
