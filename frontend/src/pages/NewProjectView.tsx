import { useState } from 'react';
import CategoryUpload from '../components/common/CategoryUpload';

export type CategoryKey = 'worldview' | 'settings' | 'scenario';

interface NewProjectViewProps {
  files: Record<CategoryKey, Array<{id: string, name: string}>>;
  onAddFiles: (category: CategoryKey, files: File[]) => void;
  onRemoveFile: (category: CategoryKey, id: string) => void;
  onBuildGraph: (track: 'ws' | 'sc') => void;
  graphBuilt: { ws: boolean; sc: boolean };
  onAnalyze: () => void;
}

export default function NewProjectView({
  files, onAddFiles, onRemoveFile, onBuildGraph, graphBuilt, onAnalyze
}: NewProjectViewProps) {
  const [showGuide, setShowGuide] = useState(true);

  const hasWsFiles = files.worldview.length > 0 || files.settings.length > 0;
  const hasScFiles = files.scenario.length > 0;
  const hasAnyFiles = hasWsFiles || hasScFiles;
  const anyGraphBuilt = graphBuilt.ws || graphBuilt.sc;

  return (
    <div className="fade flex flex-col gap-5 max-w-[700px]">
      <div>
        <h2 className="serif text-[22px] font-bold text-[#2c2416] mb-1.5">새 작품 분석 시작하기</h2>
        <p className="text-[13px] text-[#6b5c47] leading-relaxed">
          분석할 파일을 올려주세요. 세계관이나 설정집이 있으면 더 정확하게 분석할 수 있어요.
        </p>
      </div>

      {/* 온보딩 가이드 */}
      {showGuide && (
        <div className="bg-[#fef3db] border border-[rgba(196,124,26,0.2)] rounded-xl p-3.5 relative">
          <button
            onClick={() => setShowGuide(false)}
            className="absolute top-2.5 right-2.5 text-[#a89880] hover:text-[#6b5c47] text-sm"
          >✕</button>
          <div className="text-xs font-semibold text-[#c47c1a] mb-2">💡 이렇게 하면 더 좋아요</div>
          <div className="grid grid-cols-3 gap-2">
            {[
              { label: "시나리오만", items: ["🎬"], q: "기본", c: "#a89880" },
              { label: "설정집 포함", items: ["📋", "🎬"], q: "더 정확", c: "#c47c1a" },
              { label: "전체 포함", items: ["🌍", "📋", "🎬"], q: "가장 정확 ⭐", c: "#c4622d" }
            ].map(x => (
              <div key={x.label} className="bg-white/60 rounded-lg p-2.5 text-center">
                <div className="text-[9px] font-bold mb-1" style={{ color: x.c }}>{x.q}</div>
                <div className="text-[11px] font-semibold mb-1.5 text-[#2c2416]">{x.label}</div>
                <div className="flex justify-center gap-1">
                  {x.items.map(i => <span key={i} className="text-base">{i}</span>)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 파일 업로드 그리드 */}
      <div className="grid grid-cols-3 gap-3">
        {(['worldview', 'settings', 'scenario'] as CategoryKey[]).map(k => (
          <CategoryUpload
            key={k}
            categoryKey={k}
            files={files[k]}
            onAddFiles={onAddFiles}
            onRemoveFile={onRemoveFile}
          />
        ))}
      </div>

      {/* GraphRAG 구축 버튼 */}
      {hasAnyFiles && (
        <div className={`grid gap-2 ${hasWsFiles && hasScFiles ? 'grid-cols-2' : 'grid-cols-1'}`}>
          {hasWsFiles && (
            <button
              onClick={() => onBuildGraph('ws')}
              className={`py-3 rounded-xl border text-xs font-semibold transition-all ${
                graphBuilt.ws
                  ? 'border-[rgba(45,122,86,0.3)] bg-[#e8f4ee] text-[#2d7a56]'
                  : 'border-[#ede4d8] bg-white text-[#2c2416] hover:border-[#c4622d] hover:text-[#c4622d]'
              }`}
              style={{ boxShadow: "0 2px 8px rgba(44,36,22,0.06)" }}
            >
              {graphBuilt.ws ? "✅ 세계관·설정 분석 완료" : "🌍📋 세계관·설정 분석 준비하기"}
            </button>
          )}
          {hasScFiles && (
            <button
              onClick={() => onBuildGraph('sc')}
              className={`py-3 rounded-xl border text-xs font-semibold transition-all ${
                graphBuilt.sc
                  ? 'border-[rgba(45,122,86,0.3)] bg-[#e8f4ee] text-[#2d7a56]'
                  : 'border-[#ede4d8] bg-white text-[#2c2416] hover:border-[#c4622d] hover:text-[#c4622d]'
              }`}
              style={{ boxShadow: "0 2px 8px rgba(44,36,22,0.06)" }}
            >
              {graphBuilt.sc ? "✅ 시나리오 분석 완료" : "🎬 시나리오 분석 준비하기"}
            </button>
          )}
        </div>
      )}

      {/* 모순 탐지 시작 */}
      {anyGraphBuilt && (
        <button
          onClick={onAnalyze}
          className="w-full py-4 rounded-xl font-bold text-[14px] text-white flex items-center justify-center gap-2 transition-all hover:-translate-y-0.5"
          style={{
            background: "#c4622d",
            boxShadow: "0 4px 20px rgba(196,98,45,0.3)"
          }}
        >
          🔍 모순 탐지 시작하기
        </button>
      )}
    </div>
  );
}
