import { useState, useEffect } from 'react';
import Sidebar from './components/layout/Sidebar';
import Header from './components/layout/Header';
import ProgressOverlay from './components/common/ProgressOverlay';
import type { ProgressStep } from './components/common/ProgressOverlay';
import NewProjectView from './pages/NewProjectView';
import type { CategoryKey } from './pages/NewProjectView';
import ProjectDetailView from './pages/ProjectDetailView';

import type { Project, StagedFix } from './types';
import { sourceApi, analyzeApi, versionApi, statsApi, confirmationApi, resetApi } from './api/endpoints';



const CONFIRMATION_TYPE_LABELS: Record<string, string> = {
  flashback_check: "회상 장면 확인",
  intentional_change: "의도적 설정 변경",
  foreshadowing: "복선 가능성",
  source_conflict: "소스 간 충돌",
  unreliable_narrator: "비신뢰 서술자",
  timeline_ambiguity: "시간 순서 불명확",
  relationship_ambiguity: "관계 불명확",
  emotion_shift: "감정 급변",
  item_discrepancy: "소유물 불일치",
}

const CONTRADICTION_TYPE_LABELS: Record<string, string> = {
  information_asymmetry: "정보 비대칭",
  timeline: "타임라인 오류",
  relationship: "관계 충돌",
  trait: "성격·설정 충돌",
  emotion: "감정 일관성 오류",
  item: "소유물 추적 오류",
  deception: "거짓말·기만 오류",
}

const ANALYZE_STEPS: ProgressStep[] = [
  { l: "GraphRAG 지식 조회...", ms: 1000 },
  { l: "캐릭터 정보 비교...", ms: 1500 },
  { l: "7가지 모순 분석...", ms: 2000 },
  { l: "LLM 검증...", ms: 1800 },
  { l: "리포트 생성...", ms: 600 }
];

const REUPLOAD_STEPS: ProgressStep[] = [
  { l: "파일 업로드...", ms: 800 },
  { l: "문서 파싱 및 청킹...", ms: 1200 },
  { l: "GraphRAG 증분 재구축...", ms: 2000 },
  { l: "새 버전 생성...", ms: 600 }
];

const PUSH_STEPS: ProgressStep[] = [
  { l: "수정사항 원본 반영...", ms: 800 },
  { l: "변경 영역 재파싱...", ms: 1200 },
  { l: "GraphRAG 증분 업데이트...", ms: 1500 },
  { l: "인덱스 갱신...", ms: 800 }
];

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [initialLoading, setInitialLoading] = useState(true);

  const [tab, setTab] = useState("overview");
  const [staged, setStaged] = useState<StagedFix[]>([]);
  const [showAi, setShowAi] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [progress, setProgress] = useState<{ steps: ProgressStep[]; step: number; title: string } | null>(null);

  // New project state
  const [nFiles, setNFiles] = useState<Record<CategoryKey, Array<{id: string, name: string}>>>({
    worldview: [], settings: [], scenario: []
  });
  const [pendingFiles, setPendingFiles] = useState<Record<CategoryKey, Array<{id: string, name: string, file: File}>>>({
    worldview: [], settings: [], scenario: []
  });
  const activeProj = projects.find(p => p.id === activeId);

  // --- 서버 데이터 초기 로드 ---
  const withTimeout = <T,>(p: Promise<T>, ms: number): Promise<T> =>
    Promise.race([p, new Promise<T>((_, reject) => setTimeout(() => reject(new Error('timeout')), ms))]);

  const loadServerData = async (retries = 1): Promise<void> => {
    const [sourcesRes, statsRes, versionsRes, confirmationsRes] = await Promise.allSettled([
      withTimeout(sourceApi.list(), 7000),
      withTimeout(statsApi.getKbStats(), 7000),
      withTimeout(versionApi.listVersions(), 7000),
      withTimeout(confirmationApi.list(), 7000),
    ]);

    const sources: any[] = sourcesRes.status === 'fulfilled' ? sourcesRes.value : [];
    const stats: any   = statsRes.status === 'fulfilled'   ? statsRes.value   : {};
    const versions: any[] = versionsRes.status === 'fulfilled' ? versionsRes.value : [];
    const confirmations: any[] = confirmationsRes.status === 'fulfilled' ? confirmationsRes.value : [];

    if (sourcesRes.status === 'rejected') console.error('sources 로드 실패:', sourcesRes.reason);
    if (statsRes.status === 'rejected')   console.error('stats 로드 실패:',   statsRes.reason);

    // 실패하거나 빈 경우 재시도 (Gremlin 첫 연결 지연 대응)
    if (sources.length === 0 && retries > 0) {
      await new Promise(r => setTimeout(r, 1500));
      return loadServerData(retries - 1);
    }

    if (sources.length === 0) return;

    const proj: Project = {
      id: 'server',
      name: sources[0]?.name?.split('_')[0] || '현재 프로젝트',
      date: new Date().toISOString().slice(0, 10),
      kb: {
        characters: stats.characters   ?? 0,
        facts:       stats.facts        ?? 0,
        relationships: stats.relationships ?? 0,
        events:      stats.events       ?? 0,
        traits:      stats.traits       ?? 0,
      },
      sources: sources.map((s: any) => ({
        id: s.id || s.source_id,
        n: s.name,
        cat: (s.source_type || s.type || 'worldview') as 'worldview' | 'settings' | 'scenario',
        ent: s.extracted_entities || 0,
        fct: 0,
      })),
      graphBuilt: {
        ws: sources.some((s: any) => ['worldview', 'settings'].includes(s.source_type || s.type || '')),
        sc: sources.some((s: any) => (s.source_type || s.type) === 'scenario'),
      },
      contradictions: confirmations.map((c: any) => ({
        id: c.id,
        sv: 'warning' as const,
        tp: CONFIRMATION_TYPE_LABELS[c.confirmation_type] ?? c.confirmation_type,
        ch: '사용자 확인 필요',
        ft: '',
        dl: '',
        ds: c.question || c.context_summary || '',
        ev: (c.source_excerpts || []).map((e: any) => ({ sr: e.source_name || '', lc: e.source_location || '', tx: e.text || '' })),
        cf: 0,
        sg: c.context_summary || '',
        al: null,
      })),
      versions: versions.map((v: any) => ({
        id: v.id,
        vr: v.version,
        dt: v.date,
        fx: v.fixes_count,
        ds: v.description,
      })),
    };

    setProjects([proj]);
    setActiveId('server');
  };

  useEffect(() => {
    loadServerData().finally(() => setInitialLoading(false));
  }, []);

  // --- Helpers ---
  const runProgress = async (steps: ProgressStep[], title: string, callApi: () => Promise<void>) => {
    setProgress({ steps, step: 0, title });
    
    // Mix API call with visual progress steps
    try {
      // Start API call in background
      const apiPromise = callApi();
      
      // Run visual steps
      for (let s = 0; s < steps.length; s++) {
        setProgress(p => p ? { ...p, step: s } : null);
        await new Promise(resolve => setTimeout(resolve, steps[s].ms || 1000));
      }
      
      // Wait for API to completely finish
      await apiPromise;
      
    } catch (e) {
      console.error(e);
      alert("처리 중 예기치 못한 오류가 발생했습니다.");
    } finally {
      setTimeout(() => setProgress(null), 300);
    }
  };

  // --- Handlers ---
  const onSelectProj = (id: string) => {
    setActiveId(id); setIsNew(false); setTab("overview"); setStaged([]); setShowAi(false);
    setSidebarOpen(false);
  };
  
  const RESET_STEPS: ProgressStep[] = [
    { l: "그래프 데이터 삭제 중...", ms: 800 },
    { l: "스토리지 파일 삭제 중...", ms: 1000 },
    { l: "AI Search 인덱스 재생성 중...", ms: 1500 },
  ];

  const onResetAll = () => {
    runProgress(RESET_STEPS, "전체 데이터 초기화 중", async () => {
      await resetApi.resetAll();
      setProjects([]);
      setActiveId(null);
      setIsNew(false);
      setNFiles({ worldview: [], settings: [], scenario: [] });
      setPendingFiles({ worldview: [], settings: [], scenario: [] });
      setStaged([]);
    });
  };

  const onRenameProject = (id: string, name: string) => {
    setProjects(p => p.map(x => x.id === id ? { ...x, name } : x));
  };

  const onNewProj = () => {
    setIsNew(true); setActiveId(null);
    setNFiles({ worldview: [], settings: [], scenario: [] });
    setPendingFiles({ worldview: [], settings: [], scenario: [] });
    setTab("overview"); setStaged([]); setShowAi(false);
    setSidebarOpen(false);
  };

  // New Project View handlers
  const onAddFiles = (cat: CategoryKey, files: File[]) => {
    const additions = files.map((f, i) => ({ id: `f-${Date.now()}-${i}`, name: f.name, file: f }));
    setPendingFiles(p => ({ ...p, [cat]: [...p[cat], ...additions] }));
  };

  const onRemovePending = (cat: CategoryKey, id: string) => {
    setPendingFiles(p => ({ ...p, [cat]: p[cat].filter(f => f.id !== id) }));
  };

  const onRemoveFile = (cat: CategoryKey, id: string) => {
    setNFiles(p => ({ ...p, [cat]: p[cat].filter(f => f.id !== id) }));
  };

  const UPLOAD_STEPS: ProgressStep[] = [
    { l: "파일 업로드 중...", ms: 1200 },
    { l: "문서 파싱 및 청킹...", ms: 1500 },
    { l: "지식베이스 구축 중...", ms: 2000 },
    { l: "인덱싱 완료...", ms: 600 },
  ];

  const onConfirmUpload = () => {
    const allPending = (Object.entries(pendingFiles) as [CategoryKey, typeof pendingFiles[CategoryKey]][])
      .flatMap(([cat, files]) => files.map(f => ({ cat, ...f })));
    if (allPending.length === 0) return;

    runProgress(UPLOAD_STEPS, `파일 업로드 중 (${allPending.length}개)`, async () => {
      for (const f of allPending) {
        await sourceApi.upload(f.file, f.cat);
        setNFiles(p => ({ ...p, [f.cat]: [...p[f.cat], { id: f.id, name: f.name }] }));
      }
      setPendingFiles({ worldview: [], settings: [], scenario: [] });
    });
  };

  const onNewAnalyze = () => {
    runProgress(ANALYZE_STEPS, "모순 탐지 분석 중", async () => {
      const res = await analyzeApi.scan();
      const stats = await statsApi.getKbStats();
      
      const np: Project = {
        id: `p-${Date.now()}`,
        name: `새 프로젝트 ${projects.length + 1}`,
        date: new Date().toISOString().slice(0, 10),
        kb: stats,
        sources: Object.entries(nFiles).flatMap(([cat, fs]) =>
          fs.map(f => ({ id: f.id, n: f.name, cat: cat as 'worldview'|'settings'|'scenario', ent: 10, fct: 5 }))
        ),
        graphBuilt: { ws: true, sc: true },
        contradictions: [
          ...res.contradictions.map((c: any) => ({
            id: c.id, sv: ({ critical: 'critical', major: 'warning', minor: 'info' } as Record<string, string>)[c.severity?.toLowerCase()] as any ?? 'info', tp: CONTRADICTION_TYPE_LABELS[c.type] ?? c.type, ch: c.character_name || '일반',
            ft: c.location || '정보', dl: c.dialogue || '', ds: c.description,
            ev: (c.evidence || []).map((e: any) => ({ sr: e.source_name, lc: e.source_location, tx: e.text })),
            cf: c.confidence, sg: c.suggestion || '', al: c.alternative || null, ot: c.original_text || '',
            chunkId: c.chunk_id || '', chunkContent: c.chunk_content || '',
          })),
          ...(res.confirmations || []).map((c: any) => ({
            id: c.id, sv: 'warning' as any, tp: CONFIRMATION_TYPE_LABELS[c.confirmation_type] ?? c.confirmation_type, ch: '사용자 확인 필요',
            ft: '', dl: '', ds: c.question || c.context_summary || '',
            ev: (c.source_excerpts || []).map((e: any) => ({ sr: e.source_name || '', lc: e.source_location || '', tx: e.text || '' })),
            cf: 0, sg: c.context_summary || '', al: null, ot: '',
          })),
        ],
        versions: [{ id: "v1", vr: "v1.0", dt: new Date().toLocaleString("ko-KR"), fx: 0, ds: "최초 업로드" }]
      };
      setProjects(p => [np, ...p]);
      setActiveId(np.id);
      setIsNew(false);
      setTab("overview");
    });
  };

  // Existing Project Details handlers
  const onAnalyze = () => {
    if (!activeProj) return;
    runProgress(ANALYZE_STEPS, "모순 탐지 분석 중", async () => {
      const res = await analyzeApi.scan();
      
      // Transform API response
      const transformedContradictions = [
        ...res.contradictions.map((c: any) => ({
          id: c.id,
          sv: ({ critical: 'critical', major: 'warning', minor: 'info' } as Record<string, string>)[c.severity?.toLowerCase()] as any ?? 'info',
          tp: CONTRADICTION_TYPE_LABELS[c.type] ?? c.type,
          ch: c.character_name || '일반',
          ft: c.location || '분석 결과',
          dl: c.dialogue || '',
          ds: c.description,
          ev: (c.evidence || []).map((e: any) => ({ sr: e.source_name, lc: e.source_location, tx: e.text })),
          cf: c.confidence,
          sg: c.suggestion || '',
          al: c.alternative || null,
          ot: c.original_text || '',
          chunkId: c.chunk_id || '',
          chunkContent: c.chunk_content || '',
        })),
        ...(res.confirmations || []).map((c: any) => ({
          id: c.id,
          sv: 'warning' as any,
          tp: CONFIRMATION_TYPE_LABELS[c.confirmation_type] ?? c.confirmation_type,
          ch: '사용자 확인 필요',
          ft: '',
          dl: '',
          ds: c.question || c.context_summary || '',
          ev: (c.source_excerpts || []).map((e: any) => ({ sr: e.source_name || '', lc: e.source_location || '', tx: e.text || '' })),
          cf: 0,
          sg: c.context_summary || '',
          al: null,
          ot: '',
        })),
      ];

      const updated = { ...activeProj, contradictions: transformedContradictions };
      setProjects(p => p.map(x => x.id === updated.id ? updated : x));
      setTab("contradictions");
    });
  };

  const onStageFix = async (fx: StagedFix) => {
    try {
      if (fx.isIntentional) {
        await versionApi.stageIntentional(fx.id, fx.intentNote || "");
      } else {
        await versionApi.stageFix(fx.id, fx.ot || "", fx.fixedText || "", fx.chunkId || "");
      }
    } catch (e) {
      console.error(e);
    }
    setStaged(p => {
      if (p.find(s => s.id === fx.id)) return p.map(s => s.id === fx.id ? fx : s);
      return [...p, fx];
    });
  };
  
  const onUnstageFix = (id: string) => {
    versionApi.unstageFix(id).catch(e => console.error('unstage failed', e));
    setStaged(p => p.filter(s => s.id !== id));
  };

  const onReupload = (srcId: string, _srcName: string, file: File) => {
    if (!activeProj) return;
    runProgress(REUPLOAD_STEPS, "파일 재업로드 및 GraphRAG 재구축", async () => {
      await sourceApi.reupload(srcId, file);
      const nv = {
        id: `v-${Date.now()}`,
        vr: `v${(activeProj.versions.length + 1)}.0`,
        dt: new Date().toLocaleString("ko-KR"),
        fx: 0,
        ds: `파일 재업로드: ${file.name}`,
        src: file.name
      };
      const updated = { ...activeProj, versions: [nv, ...activeProj.versions] };
      setProjects(p => p.map(x => x.id === updated.id ? updated : x));
    });
  };

  const onPushFixes = () => {
    if (!activeProj || staged.length === 0) return;
    runProgress(PUSH_STEPS, "수정사항 반영 및 GraphRAG 재구축", async () => {
      const vInfo = await versionApi.pushFixes();
      
      const ids = new Set(staged.map(s => s.id));
      const nv = {
        id: vInfo.id,
        vr: vInfo.version,
        dt: vInfo.date,
        fx: vInfo.fixes_count,
        ds: vInfo.description,
        src: vInfo.src || '',
      };
      
      const updated = {
        ...activeProj,
        contradictions: activeProj.contradictions.filter(c => !ids.has(c.id)),
        versions: [nv, ...activeProj.versions]
      };
      setProjects(p => p.map(x => x.id === updated.id ? updated : x));
      setStaged([]);
    });
  };

  return (
    <div className="flex h-screen bg-[#fdfaf5] text-[#2c2416] overflow-hidden">
      {/* 모바일 사이드바 backdrop */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      <Sidebar
        projects={projects}
        activeId={activeId}
        onSelect={onSelectProj}
        onNew={onNewProj}
        onResetAll={onResetAll}
        onRenameProject={onRenameProject}
        isOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex-1 flex flex-col min-w-0">
        <Header
          activeProj={activeProj}
          isNew={isNew}
          stagedLength={staged.length}
          onToggleSidebar={() => setSidebarOpen(o => !o)}
        />

        <main className="flex-1 overflow-hidden p-6">
          {isNew && (
            <NewProjectView
              files={nFiles}
              pendingFiles={pendingFiles}
              onAddFiles={onAddFiles}
              onRemovePending={onRemovePending}
              onRemoveFile={onRemoveFile}
              onConfirmUpload={onConfirmUpload}
              onAnalyze={onNewAnalyze}
            />
          )}

          {!isNew && activeProj && (
            <ProjectDetailView
              proj={activeProj}
              tab={tab}
              setTab={setTab}
              staged={staged}
              onStageFix={onStageFix}
              onUnstageFix={onUnstageFix}
              onPushFixes={onPushFixes}
              onClearStaged={() => setStaged([])}
              onAnalyze={onAnalyze}
              onReupload={onReupload}
              showAi={showAi}
              setShowAi={setShowAi}
            />
          )}

          {!isNew && !activeProj && (
            <div className="text-center py-[80px] text-[#a89880]">
              {initialLoading ? (
                <>
                  <div className="text-4xl mb-4 animate-pulse">⏳</div>
                  <p className="text-sm">서버 데이터 불러오는 중...</p>
                </>
              ) : (
                <>
                  <div className="text-5xl mb-4">📖</div>
                  <p className="text-sm mb-4">작품을 선택하거나 새 작품을 분석해보세요</p>
                  <button
                    onClick={() => {
                      setInitialLoading(true);
                      loadServerData().finally(() => setInitialLoading(false));
                    }}
                    className="text-xs text-[#a89880] hover:text-[#c4622d] underline transition-colors"
                  >
                    데이터 새로고침
                  </button>
                </>
              )}
            </div>
          )}
        </main>
      </div>

      {progress && (
        <ProgressOverlay 
          step={progress.step} 
          steps={progress.steps} 
          title={progress.title} 
        />
      )}
    </div>
  );
}
