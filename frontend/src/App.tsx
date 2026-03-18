import { useState } from 'react';
import Sidebar from './components/layout/Sidebar';
import Header from './components/layout/Header';
import ProgressOverlay from './components/common/ProgressOverlay';
import type { ProgressStep } from './components/common/ProgressOverlay';
import NewProjectView from './pages/NewProjectView';
import type { CategoryKey } from './pages/NewProjectView';
import ProjectDetailView from './pages/ProjectDetailView';

import type { Project } from './types';
import { sourceApi, graphApi, analyzeApi, versionApi, statsApi } from './api/endpoints';

// MOCK DATA as fallback
const INITIAL_PROJECTS: Project[] = [
  {
    id: "p1", name: "그림자의 비밀 시즌1", date: "2026-03-10",
    kb: { characters: 12, facts: 47, relationships: 83, events: 156, traits: 24 },
    sources: [
      { id: "s1", n: "판타지_세계관_설정.pdf", cat: "worldview", ent: 18, fct: 22 },
      { id: "s2", n: "캐릭터_설정집_v2.txt", cat: "settings", ent: 14, fct: 19 },
      { id: "s3", n: "그림자의_비밀_시즌1.pdf", cat: "scenario", ent: 34, fct: 47 }
    ],
    graphBuilt: { ws: true, sc: true },
    contradictions: [],
    versions: []
  }
];

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
  { l: "4가지 모순 분석...", ms: 2000 },
  { l: "LLM 검증...", ms: 1800 },
  { l: "리포트 생성...", ms: 600 }
];

const PUSH_STEPS: ProgressStep[] = [
  { l: "수정사항 원본 반영...", ms: 800 },
  { l: "변경 영역 재파싱...", ms: 1200 },
  { l: "GraphRAG 증분 업데이트...", ms: 1500 },
  { l: "인덱스 갱신...", ms: 800 }
];

export default function App() {
  const [projects, setProjects] = useState<Project[]>(INITIAL_PROJECTS);
  const [activeId, setActiveId] = useState<string | null>("p1");
  const [isNew, setIsNew] = useState(false);
  
  const [tab, setTab] = useState("overview");
  const [staged, setStaged] = useState<any[]>([]);
  const [showAi, setShowAi] = useState(false);
  
  const [progress, setProgress] = useState<{ steps: ProgressStep[]; step: number; title: string } | null>(null);

  // New project state
  const [nFiles, setNFiles] = useState<Record<CategoryKey, Array<{id: string, name: string}>>>({
    worldview: [], settings: [], scenario: []
  });
  const [nGB, setNGB] = useState({ ws: false, sc: false });

  const activeProj = projects.find(p => p.id === activeId);

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
        contradictions: res.contradictions.map(c => ({
          id: c.id, sv: c.severity.toLowerCase() as any, tp: c.type, ch: c.character_name || 'System',
          ft: '정보', dl: '', ds: c.description, ev: [], cf: c.confidence, sg: c.suggestion, al: null, ui: false
        })),
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
      const transformedContradictions = res.contradictions.map(c => ({
        id: c.id, 
        sv: c.severity.toLowerCase() as any, 
        tp: c.type, 
        ch: c.character_name || 'System',
        ft: '분석 결과', 
        dl: '', 
        ds: c.description, 
        ev: [], 
        cf: c.confidence, 
        sg: c.suggestion, 
        al: null, 
        ui: false
      }));

      const updated = { ...activeProj, contradictions: transformedContradictions };
      setProjects(p => p.map(x => x.id === updated.id ? updated : x));
      setTab("contradictions");
    });
  };

  const onStageFix = async (fx: any) => {
    // Stage at backend
    await versionApi.stageFix(fx.id, fx.ot || "", fx.fixedText || "");
    
    setStaged(p => {
      if (p.find(s => s.id === fx.id)) return p.map(s => s.id === fx.id ? fx : s);
      return [...p, fx];
    });
  };
  
  const onUnstageFix = (id: string) => {
    setStaged(p => p.filter(s => s.id !== id));
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
        ds: vInfo.description 
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
