import { useState, useEffect } from 'react';
import Sidebar from './components/layout/Sidebar';
import Header from './components/layout/Header';
import ProgressOverlay from './components/common/ProgressOverlay';
import type { ProgressStep } from './components/common/ProgressOverlay';
import NewProjectView from './pages/NewProjectView';
import type { CategoryKey } from './pages/NewProjectView';
import ProjectDetailView from './pages/ProjectDetailView';

import type { Project, StagedFix } from './types';
import { sourceApi, graphApi, analyzeApi, versionApi, statsApi, confirmationApi } from './api/endpoints';


const BUILD_STEPS_WS: ProgressStep[] = [
  { l: "세계관/설정집 파싱...", ms: 800 },
  { l: "규칙·설정 추출...", ms: 2000 },
  { l: "캐릭터·관계 매핑...", ms: 1500 },
  { l: "GraphRAG(설정) 저장...", ms: 1200 }
];

const BUILD_STEPS_SC: ProgressStep[] = [
  { l: "시나리오 파싱...", ms: 800 },
  { l: "장면·대사 분석...", ms: 2000 },
  { l: "이벤트·정보흐름 추출...", ms: 1800 },
  { l: "GraphRAG(시나리오) 저장...", ms: 1200 }
];

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
  
  const [tab, setTab] = useState("overview");
  const [staged, setStaged] = useState<StagedFix[]>([]);
  const [showAi, setShowAi] = useState(false);
  
  const [progress, setProgress] = useState<{ steps: ProgressStep[]; step: number; title: string } | null>(null);

  // New project state
  const [nFiles, setNFiles] = useState<Record<CategoryKey, Array<{id: string, name: string}>>>({
    worldview: [], settings: [], scenario: []
  });
  const [nGB, setNGB] = useState({ ws: false, sc: false });

  const activeProj = projects.find(p => p.id === activeId);

  // --- 서버 데이터 초기 로드 ---
  useEffect(() => {
    const loadServerData = async () => {
      const [sourcesRes, statsRes, versionsRes, confirmationsRes] = await Promise.allSettled([
        sourceApi.list(),
        statsApi.getKbStats(),
        versionApi.listVersions(),
        confirmationApi.list(),
      ]);

      const sources: any[] = sourcesRes.status === 'fulfilled' ? sourcesRes.value : [];
      const stats: any   = statsRes.status === 'fulfilled'   ? statsRes.value   : {};
      const versions: any[] = versionsRes.status === 'fulfilled' ? versionsRes.value : [];
      const confirmations: any[] = confirmationsRes.status === 'fulfilled' ? confirmationsRes.value : [];

      if (sourcesRes.status === 'rejected') console.error('sources 로드 실패:', sourcesRes.reason);
      if (statsRes.status === 'rejected')   console.error('stats 로드 실패:',   statsRes.reason);

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
          tp: c.confirmation_type,
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

    loadServerData();
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
  };
  
  const onNewProj = () => {
    setIsNew(true); setActiveId(null); 
    setNFiles({ worldview: [], settings: [], scenario: [] });
    setNGB({ ws: false, sc: false });
    setTab("overview"); setStaged([]); setShowAi(false);
  };

  // New Project View handlers
  const onAddFiles = async (cat: CategoryKey, files: File[]) => {
    // Call real API
    try {
      for (const f of files) {
        await sourceApi.upload(f, cat);
      }
      const additions = files.map((f, i) => ({ id: `f-${Date.now()}-${i}`, name: f.name }));
      setNFiles(p => ({ ...p, [cat]: [...p[cat], ...additions] }));
    } catch (e) {
      console.error(e);
      alert("파일 업로드에 실패했습니다.");
    }
  };
  
  const onRemoveFile = (cat: CategoryKey, id: string) => {
    setNFiles(p => ({ ...p, [cat]: p[cat].filter(f => f.id !== id) }));
  };

  const onBuildGraph = (track: 'ws' | 'sc') => {
    runProgress(track === 'ws' ? BUILD_STEPS_WS : BUILD_STEPS_SC, 
      track === 'ws' ? "세계관·설정 GraphRAG 구축" : "시나리오 GraphRAG 구축", 
      async () => {
        await graphApi.build(track);
        setNGB(p => ({ ...p, [track]: true }));
      }
    );
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
        graphBuilt: nGB,
        contradictions: [
          ...res.contradictions.map((c: any) => ({
            id: c.id, sv: ({ critical: 'critical', major: 'warning', minor: 'info' } as Record<string, string>)[c.severity?.toLowerCase()] as any ?? 'info', tp: c.type, ch: c.character_name || 'System',
            ft: c.location || '정보', dl: c.dialogue || '', ds: c.description,
            ev: (c.evidence || []).map((e: any) => ({ sr: e.source_name, lc: e.source_location, tx: e.text })),
            cf: c.confidence, sg: c.suggestion || '', al: c.alternative || null, ot: c.original_text || '',
          })),
          ...(res.confirmations || []).map((c: any) => ({
            id: c.id, sv: 'warning' as any, tp: c.confirmation_type, ch: '사용자 확인 필요',
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
      // Actually fetch fresh contradictions via API
      const res = await analyzeApi.analyze("Mock content"); // In real app, we might pass the file
      
      // Transform API response
      const transformedContradictions = [
        ...res.contradictions.map((c: any) => ({
          id: c.id,
          sv: ({ critical: 'critical', major: 'warning', minor: 'info' } as Record<string, string>)[c.severity?.toLowerCase()] as any ?? 'info',
          tp: c.type,
          ch: c.character_name || 'System',
          ft: c.location || '분석 결과',
          dl: c.dialogue || '',
          ds: c.description,
          ev: (c.evidence || []).map((e: any) => ({ sr: e.source_name, lc: e.source_location, tx: e.text })),
          cf: c.confidence,
          sg: c.suggestion || '',
          al: c.alternative || null,
          ot: c.original_text || '',
        })),
        ...(res.confirmations || []).map((c: any) => ({
          id: c.id,
          sv: 'warning' as any,
          tp: c.confirmation_type,
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
        await versionApi.stageFix(fx.id, fx.ot || "", fx.fixedText || "");
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
    <div className="flex h-screen bg-[#09090b] text-[#e4e4e7] overflow-hidden">
      <Sidebar 
        projects={projects} 
        activeId={activeId} 
        onSelect={onSelectProj} 
        onNew={onNewProj} 
      />
      
      <div className="flex-1 flex flex-col min-w-0">
        <Header 
          activeProj={activeProj} 
          isNew={isNew} 
          stagedLength={staged.length} 
        />
        
        <main className="flex-1 overflow-auto p-5">
          {isNew && (
            <NewProjectView 
              files={nFiles} 
              onAddFiles={onAddFiles} 
              onRemoveFile={onRemoveFile} 
              onBuildGraph={onBuildGraph} 
              graphBuilt={nGB} 
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
            <div className="text-center py-[60px] text-[#3f3f46]">
              <p>프로젝트를 선택하거나 새 프로젝트를 생성하세요</p>
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
