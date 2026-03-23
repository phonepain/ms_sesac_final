import { fetchApi } from './client';

// ==========================================
// 1. 소스 관리 API
// ==========================================

export interface Source {
  id: string;
  name: string;
  type: string;
  status: string;
  [key: string]: any;
}

export interface IngestResponse {
  source_id: string;
  source_name: string;
  status: string;
  stats: Record<string, any>;
  extracted_entities: number;
}

export const sourceApi = {
  upload: (file: File, sourceType: 'worldview' | 'settings' | 'scenario') => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('source_type', sourceType);
    
    return fetchApi<IngestResponse>('/sources/upload', {
      method: 'POST',
      body: formData,
      // Note: Do not set Content-Type header manually for FormData
    });
  },
  
  list: () => fetchApi<Source[]>('/sources'),

  download: async (id: string): Promise<Blob> => {
    const res = await fetch(`/api/sources/${id}/download`);
    if (!res.ok) throw new Error(`Download failed: ${res.status}`);
    return res.blob();
  },

  reupload: (id: string, file: File) => {
    const formData = new FormData();
    formData.append('file', file);
    return fetchApi<IngestResponse>(`/sources/${id}`, {
      method: 'PUT',
      body: formData,
    });
  },

  delete: (id: string) => fetchApi<{status: string, message: string}>(`/sources/${id}`, { method: 'DELETE' })
};

// ==========================================
// 2. GraphRAG 구축 API
// ==========================================

export const graphApi = {
  build: (track: 'ws' | 'sc') => fetchApi<{status: string, track: string, job_id: string}>('/graph/build', {
    method: 'POST',
    body: JSON.stringify({ track })
  }),
  
  getStatus: () => fetchApi<{status: string, progress: number}>('/graph/status')
};

// ==========================================
// 3. 모순 탐지 API
// ==========================================

export interface ContradictionReport {
  id: string;
  type: string;
  severity: string;
  character_name?: string;
  description: string;
  confidence: number;
  suggestion: string;
  [key: string]: any;
}

export interface UserConfirmation {
  id: string;
  confirmation_type: string;
  status: string;
  question: string;
  context_summary: string;
  source_excerpts: any[];
  [key: string]: any;
}

export interface AnalysisResponse {
  contradictions: ContradictionReport[];
  confirmations: UserConfirmation[];
  total?: number;
  [key: string]: any;
}

export const analyzeApi = {
  analyze: (content: string, title?: string) => fetchApi<AnalysisResponse>('/analyze', {
    method: 'POST',
    body: JSON.stringify({ content, title: title || 'draft' })
  }),
  
  scan: () => fetchApi<AnalysisResponse>('/scan', { method: 'POST' })
};

// ==========================================
// 4. 사용자 확인 (Review Workflow) API
// ==========================================

export const confirmationApi = {
  list: () => fetchApi<UserConfirmation[]>('/confirmations'),
  
  resolve: (id: string, decision: string, userResponse?: string) => fetchApi<{status: string, confirmation_id: string, decision: string}>(
    `/confirmations/${id}/resolve`,
    {
      method: 'POST',
      body: JSON.stringify({ decision, user_response: userResponse })
    }
  )
};

// ==========================================
// 5. 수정 반영(Fixes) 및 버전 API
// ==========================================

export interface VersionInfo {
  id: string;
  version: string;
  date: string;
  fixes_count: number;
  description: string;
  src?: string;
}

export const versionApi = {
  stageFix: (contradictionId: string, originalText: string, fixedText: string) =>
    fetchApi<{status: string, contradiction_id: string}>('/fixes/stage', {
      method: 'POST',
      body: JSON.stringify({
        contradiction_id: contradictionId,
        original_text: originalText,
        fixed_text: fixedText
      })
    }),

  stageIntentional: (contradictionId: string, note: string) =>
    fetchApi<{status: string, contradiction_id: string}>('/fixes/stage', {
      method: 'POST',
      body: JSON.stringify({
        contradiction_id: contradictionId,
        is_intentional: true,
        intent_note: note
      })
    }),

  pushFixes: (sourceId?: string, description?: string) =>
    fetchApi<VersionInfo>('/fixes/push', {
      method: 'POST',
      body: JSON.stringify({ source_id: sourceId, description })
    }),

  listVersions: () => fetchApi<VersionInfo[]>('/versions'),

  getContent: (versionId: string) =>
    fetchApi<{content: string}>(`/versions/${versionId}/content`),

  getDiff: (versionA: string, versionB: string) =>
    fetchApi<{diff: string}>(`/versions/${versionA}/diff/${versionB}`)
};

// ==========================================
// 6. 통계 조회 API
// ==========================================

export interface KBStats {
  characters: number;
  facts: number;
  relationships: number;
  events: number;
  traits: number;
  locations: number;
  items: number;
  organizations: number;
  sources: number;
  confirmations: number;
}

export const statsApi = {
  getKbStats: () => fetchApi<KBStats>('/kb/stats')
};

// ==========================================
// 7. AI 질의 API
// ==========================================

export const aiApi = {
  query: (query: string) => fetchApi<{answer: string, sources: string[]}>('/ai/query', {
    method: 'POST',
    body: JSON.stringify({ query })
  })
};
