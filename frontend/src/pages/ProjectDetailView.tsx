import { useState, useRef } from 'react';
import { SV_COLORS } from '../types';
import type { Project, SeverityType, Contradiction, StagedFix } from '../types';
import { versionApi } from '../api/endpoints';
import KbStats from '../components/project/KbStats';
import SourceList from '../components/project/SourceList';
import AiChatPanel from '../components/project/AiChatPanel';
import StagedFixes from '../components/project/StagedFixes';
import ContradictionCard from '../components/project/ContradictionCard';

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

const formatDate = (dt: string) => {
  try {
    return new Date(dt).toLocaleString('ko-KR', {
      timeZone: 'Asia/Seoul',
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    }).replace(/\. /g, '-').replace('.', '').replace(',', '');
  } catch {
    return dt;
  }
};

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
        const res = await versionApi.getContent(vId);
        data = res.content;
      } else if (type === 'diff' && prevId) {
        const res = await versionApi.getDiff(prevId, vId);
        data = res.diff;
      }
      setVersionPanels(p => ({ ...p, [vId]: { type, data } }));
    } catch {
      setVersionPanels(p => ({ ...p, [vId]: { type, data: '(불러오기 실패)' } }));
    }
  };

  const filterLabels: Record<string, string> = {
    all: '전체',
    critical: `🔴 ${SV_COLORS.critical.l}`,
    warning: `🟡 ${SV_COLORS.warning.l}`,
    info: `🟢 ${SV_COLORS.info.l}`,
  };

  return (
    <div className="fade flex flex-col gap-4" style={{ height: '100%' }}>
      {/* 프로젝트 헤더 */}
      <div className="flex items-center justify-between flex-wrap gap-y-2 shrink-0">
        <div>
          <h2 className="serif text-xl font-bold text-[#2c2416]">{proj.name}</h2>
          <p className="text-[#a89880] text-[11px] mt-0.5">{proj.date} 분석</p>
        </div>
        <button
          onClick={() => setShowAi(!showAi)}
          className={`flex items-center gap-1.5 px-4 py-2.5 rounded-[10px] text-[12px] font-bold transition-all duration-200 ${
            showAi
              ? 'bg-[#c4622d] text-white border-none shadow-[0_4px_16px_rgba(196,98,45,0.3)]'
              : 'bg-white text-[#c4622d] border border-[#c4622d] hover:bg-[#fdeee6]'
          }`}
          style={{ boxShadow: showAi ? undefined : "0 2px 10px rgba(196,98,45,0.15)" }}
        >
          🤖 {showAi ? "AI 질문 닫기" : "AI에게 질문하기"}
        </button>
      </div>

      {/* 탭 네비게이션 */}
      <div className="flex gap-1 shrink-0 overflow-x-auto pb-0.5 scrollbar-none">
        {[
          { k: "overview", l: "📊 개요" },
          { k: "contradictions", l: `⚠️ 모순${contradictions.length > 0 ? ` (${contradictions.length}건)` : ''}` },
          { k: "versions", l: "📝 수정 이력" }
        ].map(t => (
          <button
            key={t.k}
            onClick={() => setTab(t.k)}
            className={`px-3.5 py-1.5 rounded-lg text-[12px] font-semibold transition-all ${
              tab === t.k
                ? "bg-[#fdeee6] border border-[rgba(196,98,45,0.2)] text-[#c4622d]"
                : "bg-transparent border border-transparent text-[#a89880] hover:bg-[#f5efe6]"
            }`}
          >
            {t.l}
          </button>
        ))}
      </div>

      {/* 메인 콘텐츠
          [Layout Fix]
          - 바깥 div: overflow-auto는 그리드 전체에만 적용 (카드 잘림 방지)
          - 안쪽 컬럼: overflow-y-auto + flex flex-col
            → ContradictionCard에 flex-shrink:0 이 있으므로 카드가 압축되지 않음
      */}
      <div className={`flex-1 min-h-0 grid gap-4 ${showAi ? "grid-cols-1 md:grid-cols-[1fr_360px]" : "grid-cols-1"}`}>
        <div className="overflow-y-auto flex flex-col gap-3 pr-1 pb-4" style={{ minHeight: 0 }}>

          {/* 개요 탭 */}
          {tab === "overview" && (
            <>
              <KbStats stats={proj.kb} />
              <SourceList sources={proj.sources} />

              {contradictions.length === 0 ? (
                <button
                  onClick={onAnalyze}
                  className="w-full py-3.5 rounded-xl font-bold text-[13px] flex items-center justify-center gap-2 text-white transition-all hover:-translate-y-0.5"
                  style={{
                    background: "#c4622d",
                    boxShadow: "0 4px 20px rgba(196,98,45,0.25)"
                  }}
                >
                  🔍 모순 탐지 시작하기
                </button>
              ) : (
                <div
                  className="bg-[#fdeaea] border border-[rgba(184,50,50,0.2)] rounded-xl p-4 flex items-center justify-between"
                >
                  <div>
                    <div className="text-[13px] font-bold text-[#b83232]">
                      {contradictions.length}건의 모순이 발견됐어요
                    </div>
                    <div className="text-[11px] text-[#a89880] mt-1">
                      {counts.critical}건 중요, {counts.warning}건 확인 필요
                    </div>
                  </div>
                  <button
                    onClick={() => setTab("contradictions")}
                    className="text-[12px] font-semibold text-[#b83232] px-4 py-2 rounded-lg border border-[rgba(184,50,50,0.25)] bg-white hover:bg-[#fdeaea] transition-colors"
                  >
                    결과 보기 →
                  </button>
                </div>
              )}
            </>
          )}

          {/* 모순 탭 */}
          {tab === "contradictions" && (
            <>
              <StagedFixes
                staged={staged}
                onRemove={onUnstageFix}
                onPush={onPushFixes}
                onClear={onClearStaged}
              />

              {/* 필터 */}
              <div className="flex gap-1.5 flex-wrap mb-1">
                {(['all', 'critical', 'warning', 'info'] as const).map(f => {
                  const isActive = filter === f;
                  const sv = f === 'all' ? null : SV_COLORS[f];
                  return (
                    <button
                      key={f}
                      onClick={() => setFilter(f)}
                      className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-all ${
                        isActive
                          ? (f === 'all' ? 'bg-white border border-[#ede4d8] text-[#2c2416]' : '')
                          : 'bg-[#f5efe6] text-[#a89880] border border-transparent hover:bg-white hover:border-[#ede4d8]'
                      }`}
                      style={isActive && f !== 'all' ? {
                        background: sv?.bg, color: sv?.tx, borderColor: sv?.bd
                      } : {}}
                    >
                      {filterLabels[f]}
                      <span className="mono text-[8px] bg-white/60 px-1 py-0.5 rounded">
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
                <div className="text-center py-12 text-[#a89880]">
                  <div className="text-4xl mb-3">✨</div>
                  <div className="text-[13px]">선택한 조건의 모순이 없어요!</div>
                </div>
              )}
            </>
          )}

          {/* 버전 탭 */}
          {tab === "versions" && (
            <>
              <button
                onClick={() => versionFileRef.current?.click()}
                className="flex items-center gap-1.5 text-[11px] text-[#a89880] hover:text-[#c4622d] px-4 py-2.5 rounded-xl border border-[#ede4d8] bg-white hover:border-[rgba(196,98,45,0.3)] hover:bg-[#fdeee6] transition-colors w-full justify-center"
                style={{ boxShadow: "0 2px 8px rgba(44,36,22,0.06)" }}
              >
                📁 파일로 새 버전 만들기
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

              {/* 버전 타임라인 */}
              <div className="pl-6 relative">
                <div className="absolute left-2 top-2 bottom-2 w-0.5 bg-[#ede4d8] rounded-sm" />

                {versions.map((v, i) => {
                  const panel = versionPanels[v.id];
                  const prevId = versions[i + 1]?.id;

                  return (
                    <div key={v.id} className="relative mb-3.5">
                      <div className={`absolute -left-[19px] top-1.5 w-2.5 h-2.5 rounded-full border-2 ${
                        i === 0
                          ? 'bg-[#c4622d] border-[rgba(196,98,45,0.25)]'
                          : 'bg-[#ede4d8] border-white'
                      }`} />

                      <div
                        className={`rounded-xl p-3 border ${
                          i === 0
                            ? 'bg-white border-[rgba(196,98,45,0.2)]'
                            : 'bg-white border-[#ede4d8]'
                        }`}
                        style={{ boxShadow: "0 2px 8px rgba(44,36,22,0.06)" }}
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <div className="flex items-center gap-1.5">
                            <span className={`mono text-[12px] font-bold ${i === 0 ? 'text-[#c4622d]' : 'text-[#6b5c47]'}`}>
                              {v.vr}
                            </span>
                            {i === 0 && (
                              <span className="text-[9px] bg-[#fdeee6] text-[#c4622d] px-1.5 py-0.5 rounded">최신</span>
                            )}
                            {v.fx > 0 && (
                              <span className="text-[9px] bg-[#fef3db] text-[#c47c1a] px-1.5 py-0.5 rounded">
                                {v.fx}건 수정
                              </span>
                            )}
                            {v.src && (
                              <span className="text-[9px] bg-[#f5efe6] text-[#a89880] px-1.5 py-0.5 rounded">
                                {v.src}
                              </span>
                            )}
                          </div>
                          <span className="text-[10px] text-[#a89880]">{formatDate(v.dt)}</span>
                        </div>
                        <p className="text-[11px] text-[#6b5c47] leading-relaxed break-keep">{v.ds}</p>

                        <div className="flex gap-1.5 mt-2">
                          <button
                            onClick={() => toggleVersionPanel(v.id, 'content')}
                            className={`text-[10px] px-2 py-1 rounded border transition-colors ${
                              panel?.type === 'content'
                                ? 'text-[#c4622d] border-[rgba(196,98,45,0.3)] bg-[#fdeee6]'
                                : 'text-[#a89880] border-[#ede4d8] hover:text-[#2c2416] hover:border-[#a89880]'
                            }`}
                          >
                            원고 보기
                          </button>
                          {i < versions.length - 1 && (
                            <button
                              onClick={() => toggleVersionPanel(v.id, 'diff', prevId)}
                              className={`text-[10px] px-2 py-1 rounded border transition-colors ${
                                panel?.type === 'diff'
                                  ? 'text-[#c4622d] border-[rgba(196,98,45,0.3)] bg-[#fdeee6]'
                                  : 'text-[#a89880] border-[#ede4d8] hover:text-[#2c2416] hover:border-[#a89880]'
                              }`}
                            >
                              이전 버전과 비교
                            </button>
                          )}
                        </div>

                        {panel && (
                          <div className="mt-2.5 bg-[#f5efe6] rounded-lg p-2.5 text-[10px] font-mono text-[#6b5c47] whitespace-pre-wrap max-h-[200px] overflow-auto">
                            {panel.data || '(내용 없음)'}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })}

                {versions.length === 0 && (
                  <div className="text-center py-8 text-[#a89880] text-[12px]">수정 이력이 없습니다</div>
                )}
              </div>
            </>
          )}
        </div>

        {showAi && (
          <div className="overflow-y-auto min-h-0 max-h-[50vh] md:max-h-none">
            <AiChatPanel />
          </div>
        )}
      </div>
    </div>
  );
}
