import { useState, useRef } from 'react';
import { SV_COLORS } from '../types';
import type { Project, SeverityType, Contradiction, StagedFix } from '../types';
import KbStats from '../components/project/KbStats';
import SourceList from '../components/project/SourceList';
import AiChatPanel from '../components/project/AiChatPanel';
import StagedFixes from '../components/project/StagedFixes';
import ContradictionCard from '../components/project/ContradictionCard';
import { AI, Se, Up2, Bk, Df } from '../components/common/Icons';
import { versionApi } from '../api/endpoints';

interface ProjectDetailViewProps {
  proj: Project;
  tab: string;
  setTab: (tab: string) => void;
  staged: StagedFix[];
  onStageFix: (fix: StagedFix) => void;
  onUnstageFix: (id: string) => void;
  onPushFixes: () => void;
  onClearStaged: () => void;
  onAnalyze: () => void;
  onReupload?: (srcId: string, srcName: string, file: File) => void;
  showAi: boolean;
  setShowAi: (show: boolean) => void;
}

export default function ProjectDetailView({
  proj, tab, setTab, staged, onStageFix, onUnstageFix, onPushFixes, onClearStaged,
  onAnalyze, onReupload, showAi, setShowAi
}: ProjectDetailViewProps) {
  const [filter, setFilter] = useState<'all' | SeverityType>('all');
  const [versionPanels, setVersionPanels] = useState<Record<string, { type: 'content' | 'diff'; data?: string } | null>>({});
  const versionFileRef = useRef<HTMLInputElement>(null);

  const contradictions: Contradiction[] = proj.contradictions || [];
  const stagedIds = new Set(staged.map(s => s.id));

  const filtered = filter === 'all' ? contradictions : contradictions.filter(c => c.sv === filter);

  const counts = {
    all: contradictions.length,
    critical: contradictions.filter(c => c.sv === 'critical').length,
    warning: contradictions.filter(c => c.sv === 'warning').length,
    info: contradictions.filter(c => c.sv === 'info').length
  };

  const versions = proj.versions || [];

  const toggleVersionPanel = async (vId: string, type: 'content' | 'diff', prevId?: string) => {
    const current = versionPanels[vId];
    if (current?.type === type) {
      setVersionPanels(p => ({ ...p, [vId]: null }));
      return;
    }
    try {
      let data = '';
      if (type === 'content') {
        const res = await fetch(`/api/versions/${vId}/content`);
        data = await res.text();
      } else if (type === 'diff' && prevId) {
        const res = await fetch(`/api/versions/${prevId}/diff/${vId}`);
        data = await res.text();
      }
      setVersionPanels(p => ({ ...p, [vId]: { type, data } }));
    } catch {
      setVersionPanels(p => ({ ...p, [vId]: { type, data: '(불러오기 실패)' } }));
    }
  };

  return (
    <div className="fade flex flex-col gap-3.5 h-full">
      {/* Header */}
      <div className="flex items-center justify-between shrink-0">
        <div>
          <h2 className="text-[17px] font-black text-white">{proj.name}</h2>
          <p className="text-[#52525b] text-[10px]">{proj.date}</p>
        </div>

        <button
          onClick={() => setShowAi(!showAi)}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-[9px] text-xs font-semibold text-white transition-all duration-200 ${
            showAi
              ? 'bg-gradient-to-br from-[#059669] to-[#0d9488] border-none shadow-[0_4px_16px_rgba(16,185,129,0.3)]'
              : 'bg-gradient-to-br from-[rgba(16,185,129,0.15)] to-[rgba(13,148,136,0.15)] border border-[rgba(16,185,129,0.3)] shadow-[0_2px_8px_rgba(16,185,129,0.1)]'
          }`}
        >
          <AI /> {showAi ? "AI 질의 닫기" : "AI 질의"}
        </button>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 shrink-0">
        {[
          { k: "overview", l: "개요" },
          { k: "contradictions", l: `모순 ${contradictions.length > 0 ? contradictions.length : ""}` },
          { k: "versions", l: "버전" }
        ].map(t => (
          <button
            key={t.k}
            onClick={() => setTab(t.k)}
            className={`px-3 py-1.5 rounded-md text-[11px] font-bold transition-colors ${
              tab === t.k
                ? "bg-[rgba(16,185,129,0.08)] border border-[rgba(16,185,129,0.12)] text-[#34d399]"
                : "bg-transparent border border-transparent text-[#71717a] hover:bg-[rgba(39,39,42,0.4)]"
            }`}
          >
            {t.l}
          </button>
        ))}
      </div>

      {/* Main Content Area */}
      <div className={`flex-1 overflow-auto grid gap-3.5 pb-20 ${showAi ? "grid-cols-[1fr_380px]" : "grid-cols-1"}`}>
        <div className="overflow-auto flex flex-col gap-3 pr-2 scrollbar-thin">

          {tab === "overview" && (
            <>
              <KbStats stats={proj.kb} />
              <SourceList sources={proj.sources} onReupload={onReupload} />

              {contradictions.length === 0 ? (
                <button
                  onClick={onAnalyze}
                  className="w-full py-3 rounded-[9px] font-semibold text-xs flex items-center justify-center gap-1.5 bg-gradient-to-r from-[#059669] to-[#0d9488] text-white hover:opacity-90 transition-opacity"
                >
                  <Se /> 모순 탐지 시작
                </button>
              ) : (
                <div className="bg-[rgba(239,68,68,0.04)] border border-[rgba(239,68,68,0.12)] rounded-[9px] p-3 flex items-center justify-between">
                  <div>
                    <span className="text-xs font-bold text-[#f87171]">{contradictions.length}건의 모순</span>
                    <span className="text-[10px] text-[#52525b] ml-1.5">발견됨</span>
                  </div>
                  <button
                    onClick={() => setTab("contradictions")}
                    className="text-[11px] font-bold text-[#f87171] px-3 py-1.5 rounded-md border border-[rgba(239,68,68,0.2)] hover:bg-[rgba(239,68,68,0.1)] transition-colors"
                  >
                    결과 보기 →
                  </button>
                </div>
              )}
            </>
          )}

          {tab === "contradictions" && (
            <>
              <StagedFixes
                staged={staged}
                onRemove={onUnstageFix}
                onPush={onPushFixes}
                onClear={onClearStaged}
              />

              <div className="flex gap-1 flex-wrap mb-1">
                {(['all', 'critical', 'warning', 'info'] as const).map(f => {
                  const isActive = filter === f;
                  const sv = f === 'all' ? null : SV_COLORS[f];

                  return (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      className={`flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-bold transition-all ${
                        isActive
                          ? (f === 'all' ? 'bg-[#3f3f46] text-white' : '')
                          : 'bg-[rgba(39,39,42,0.2)] text-[#52525b] hover:bg-[rgba(39,39,42,0.4)] border border-transparent'
                      }`}
                      style={isActive && f !== 'all' ? { backgroundColor: sv?.bg, color: sv?.tx, borderColor: sv?.bd } : {}}
                    >
                      {f === 'all' ? '전체' : sv?.l}
                      <span className="mono text-[7px] bg-[rgba(9,9,14,0.25)] px-1 py-0.5 rounded-sm">
                        {counts[f]}
                      </span>
                    </button>
                  );
                })}
              </div>

              {filtered.map((c: Contradiction) => (
                <ContradictionCard
                  key={c.id}
                  item={c}
                  isStaged={stagedIds.has(c.id)}
                  onStage={onStageFix}
                  onUnstageFix={onUnstageFix}
                />
              ))}

              {filtered.length === 0 && (
                <div className="text-center py-8 text-[#3f3f46] text-[11px]">모순이 없습니다</div>
              )}
            </>
          )}

          {tab === "versions" && (
            <>
              {/* 파일로 새 버전 만들기 */}
              <button
                onClick={() => versionFileRef.current?.click()}
                className="flex items-center gap-1.5 text-[10px] text-[#a1a1aa] hover:text-white px-3 py-2 rounded-[9px] border border-[rgba(63,63,70,0.15)] hover:border-[rgba(16,185,129,0.3)] hover:bg-[rgba(16,185,129,0.04)] transition-colors w-full justify-center"
              >
                <Up2 /> 파일로 새 버전 만들기
              </button>
              <input
                type="file"
                ref={versionFileRef}
                className="hidden"
                accept=".txt,.pdf"
                onChange={e => {
                  const file = e.target.files?.[0];
                  if (file && onReupload) onReupload('', proj.name, file);
                  e.target.value = '';
                }}
              />

              <div className="pl-5 relative">
                <div className="absolute left-1.5 top-1.5 bottom-1.5 w-[2px] bg-[rgba(63,63,70,0.2)] rounded-sm" />

                {versions.map((v, i) => {
                  const panel = versionPanels[v.id];
                  const prevId = versions[i + 1]?.id;

                  return (
                    <div key={v.id} className="relative mb-3">
                      <div className={`absolute -left-[17px] top-1 w-[9px] h-[9px] rounded-full border-2 ${
                        i === 0
                          ? 'bg-[#10b981] border-[rgba(16,185,129,0.25)]'
                          : 'bg-[#3f3f46] border-[#27272a]'
                      }`} />

                      <div className={`rounded-xl p-2.5 border ${
                        i === 0
                          ? 'bg-[rgba(16,185,129,0.03)] border-[rgba(16,185,129,0.1)]'
                          : 'bg-[rgba(39,39,42,0.08)] border-[rgba(63,63,70,0.06)]'
                      }`}>
                        <div className="flex items-center justify-between mb-1">
                          <div className="flex items-center gap-1.5">
                            <span className={`mono text-[11px] font-bold ${i === 0 ? 'text-[#34d399]' : 'text-[#a1a1aa]'}`}>
                              {v.vr}
                            </span>
                            {i === 0 && (
                              <span className="text-[7px] bg-[rgba(16,185,129,0.08)] text-[#34d399] px-1 py-0.5 rounded-sm">최신</span>
                            )}
                            {v.fx > 0 && (
                              <span className="text-[7px] bg-[rgba(245,158,11,0.06)] text-[#fbbf24] px-1 py-0.5 rounded-sm">
                                {v.fx}수정
                              </span>
                            )}
                            {v.src && (
                              <span className="text-[7px] bg-[rgba(39,39,42,0.4)] text-[#71717a] px-1 py-0.5 rounded-sm">
                                {v.src}
                              </span>
                            )}
                          </div>
                          <span className="text-[9px] text-[#52525b]">{v.dt}</span>
                        </div>
                        <p className="text-[10px] text-[#d4d4d8] leading-relaxed break-keep">{v.ds}</p>

                        <div className="flex gap-1 mt-1.5">
                          <button
                            onClick={() => toggleVersionPanel(v.id, 'content')}
                            className={`flex items-center gap-0.5 text-[8px] px-1.5 py-0.5 rounded-[3px] border transition-colors ${
                              panel?.type === 'content'
                                ? 'text-[#34d399] border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.06)]'
                                : 'text-[#52525b] border-[rgba(63,63,70,0.1)] hover:text-[#e4e4e7] hover:border-[#52525b]'
                            }`}
                          >
                            <Bk /> 원고 보기
                          </button>
                          {i < versions.length - 1 && (
                            <button
                              onClick={() => toggleVersionPanel(v.id, 'diff', prevId)}
                              className={`flex items-center gap-0.5 text-[8px] px-1.5 py-0.5 rounded-[3px] border transition-colors ${
                                panel?.type === 'diff'
                                  ? 'text-[#34d399] border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.06)]'
                                  : 'text-[#52525b] border-[rgba(63,63,70,0.1)] hover:text-[#e4e4e7] hover:border-[#52525b]'
                              }`}
                            >
                              <Df /> 비교
                            </button>
                          )}
                        </div>

                        {panel && (
                          <div className="mt-2 bg-[rgba(9,9,14,0.3)] rounded-md p-2 text-[10px] font-mono text-[#d4d4d8] whitespace-pre-wrap max-h-[200px] overflow-auto">
                            {panel.data || '(내용 없음)'}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </div>

        {showAi && <AiChatPanel />}
      </div>
    </div>
  );
}
