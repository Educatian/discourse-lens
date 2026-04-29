/// <reference types="vite/client" />
// Static JSON loaders. Files live under /<base>/data/*.json after `dlens export`.

const BASE = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");

export interface Paper {
  doi: string;
  title: string;
  journal_id: string;
  field: "LS" | "ET";
  year: number;
  authors: string[];
  abstract: string;
}

export interface JournalMeta {
  id: string;
  name: string;
  field: "LS" | "ET";
  issns: string[];
  count: number;
}
export interface JournalsMeta {
  journals: JournalMeta[];
  totals: { ls: number; et: number; all: number };
}

export interface GraphNode { id: string; freq: number; }
export interface GraphLink {
  source: string | GraphNode;
  target: string | GraphNode;
  weight: number;
  npmi: number;
  cooc: number;
}
export interface FieldNetwork {
  field: "LS" | "ET";
  nodes: GraphNode[];
  links: GraphLink[];
  n_docs: number;
}

export interface KeywordIndex {
  [keyword: string]: {
    ls: { freq: number; neighbors: { id: string; weight: number; cooc: number }[] };
    et: { freq: number; neighbors: { id: string; weight: number; cooc: number }[] };
    fuzzy_links: { id: string; score: number }[];
  };
}

export interface ThreadMeta {
  id: string;
  display_name: string;
  definition?: string;
}

export interface ThreadBias {
  ls_share: number;
  et_share: number;
  delta: number;
  delta_lo: number;
  delta_hi: number;
  p_perm: number;
  n_ls: number;
  n_et: number;
}

export interface ThreadTimeline {
  model?: string;
  provider?: string;
  years: number[];
  threads: ThreadMeta[];
  totals_per_year: { ls: number[]; et: number[] };
  series: {
    ls: Record<string, number[]>;
    et: Record<string, number[]>;
  };
  series_ci?: {
    ls: { lo: Record<string, number[]>; hi: Record<string, number[]> };
    et: { lo: Record<string, number[]>; hi: Record<string, number[]> };
  };
  bias?: Record<string, ThreadBias>;
  stats?: { n_tagged: number; n_records: number; n_boot?: number; n_perm?: number };
}

export type PaperTags = Record<string, string[]>;   // doi -> thread_ids

export interface TopicExemplar {
  doi: string;
  title: string;
  field: "LS" | "ET";
  year: number;
}
export interface BertopicTopic {
  id: number;
  size: number;
  top_words: string[];
  exemplars: TopicExemplar[];
  ls_count: number;
  et_count: number;
}
export interface TopicsArtifact {
  method: string;
  n_topics: number;
  n_outliers: number;
  topics: BertopicTopic[];
}
export interface ConfusionArtifact {
  method: string;
  topic_ids: number[];
  thread_ids: string[];
  thread_display_names: string[];
  confusion: number[][];
  diagonal_score: number;
  interpretation?: string;
}

export interface SensitivityRow {
  cosine?: number;
  npmi?: number;
  n_canonicals?: number;
  n_links?: number;
  top_k_jaccard?: number;
  neighbor_jaccard?: number;
}
export interface SensitivityArtifact {
  cosine_merge_sweep: {
    ref: number;
    top_k: number;
    fields: { ls: SensitivityRow[]; et: SensitivityRow[] };
  };
  npmi_sweep: {
    ref: number;
    n_focus_nodes: number;
    top_k_neighbors: number;
    fields: { ls: SensitivityRow[]; et: SensitivityRow[] };
  };
  interpretation?: string;
}

export interface AppData {
  papers: Paper[];
  journals: JournalsMeta;
  networkLs: FieldNetwork;
  networkEt: FieldNetwork;
  keywordIndex: KeywordIndex;
  keywordPapers?: Record<string, { ls: string[]; et: string[] }>;
  threadTimeline?: ThreadTimeline;
  paperTags?: PaperTags;
  topics?: TopicsArtifact;
  confusion?: ConfusionArtifact;
  sensitivity?: SensitivityArtifact;
}

async function fetchJson<T>(rel: string): Promise<T> {
  const url = `${BASE}/data/${rel}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} → HTTP ${res.status}`);
  return (await res.json()) as T;
}

export async function loadAllData(): Promise<AppData> {
  const [papers, journals, networkLs, networkEt, keywordIndex] = await Promise.all([
    fetchJson<Paper[]>("papers.json"),
    fetchJson<JournalsMeta>("journals.json"),
    fetchJson<FieldNetwork>("network_ls.json"),
    fetchJson<FieldNetwork>("network_et.json"),
    fetchJson<KeywordIndex>("keyword_index.json"),
  ]);
  let keywordPapers: AppData["keywordPapers"] = undefined;
  try {
    keywordPapers = await fetchJson<NonNullable<AppData["keywordPapers"]>>("keyword_papers.json");
  } catch {
    // optional artifact
  }
  let threadTimeline: ThreadTimeline | undefined;
  try {
    threadTimeline = await fetchJson<ThreadTimeline>("thread_timeline.json");
  } catch {
    // optional artifact: only present after `dlens tag` completes
  }
  let paperTags: PaperTags | undefined;
  try {
    paperTags = await fetchJson<PaperTags>("paper_tags.json");
  } catch {
    // optional artifact: only present after `dlens tag` completes
  }
  let topics: TopicsArtifact | undefined;
  let confusion: ConfusionArtifact | undefined;
  let sensitivity: SensitivityArtifact | undefined;
  try { topics = await fetchJson<TopicsArtifact>("topics.json"); } catch {}
  try { confusion = await fetchJson<ConfusionArtifact>("topic_thread_confusion.json"); } catch {}
  try { sensitivity = await fetchJson<SensitivityArtifact>("sensitivity.json"); } catch {}
  return {
    papers, journals, networkLs, networkEt, keywordIndex, keywordPapers,
    threadTimeline, paperTags, topics, confusion, sensitivity,
  };
}
