import { useState } from 'react';
import Onboarding from '../components/common/Onboarding';
import CategoryUpload from '../components/common/CategoryUpload';
import { Se } from '../components/common/Icons';

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
    <div className="fade flex flex-col gap-4">
      <h2 className="text-lg font-black text-white">새 프로젝트</h2>
      
      {showGuide && <Onboarding onClose={() => setShowGuide(false)} />}
      
      <div className="grid grid-cols-3 gap-2.5">
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

      {hasAnyFiles && (
        <div className={`grid gap-2 ${hasWsFiles && hasScFiles ? 'grid-cols-2' : 'grid-cols-1'}`}>
          {hasWsFiles && (
            <button 
              onClick={() => onBuildGraph('ws')}
              className={`p-3 rounded-lg border text-[11px] font-semibold transition-colors ${
                graphBuilt.ws 
                  ? 'border-[rgba(139,92,246,0.2)] bg-[rgba(139,92,246,0.04)] text-[#a78bfa]' 
                  : 'border-[rgba(63,63,70,0.12)] bg-[rgba(39,39,42,0.08)] text-[#e4e4e7] hover:bg-[rgba(39,39,42,0.2)]'
              }`}
            >
              {graphBuilt.ws ? "✅ 세계관·설정 완료" : "🌍📋 GraphRAG 구축"}
            </button>
          )}
          
          {hasScFiles && (
            <button 
              onClick={() => onBuildGraph('sc')}
              className={`p-3 rounded-lg border text-[11px] font-semibold transition-colors ${
                graphBuilt.sc 
                  ? 'border-[rgba(52,211,153,0.2)] bg-[rgba(52,211,153,0.04)] text-[#34d399]' 
                  : 'border-[rgba(63,63,70,0.12)] bg-[rgba(39,39,42,0.08)] text-[#e4e4e7] hover:bg-[rgba(39,39,42,0.2)]'
              }`}
            >
              {graphBuilt.sc ? "✅ 시나리오 완료" : "🎬 GraphRAG 구축"}
            </button>
          )}
        </div>
      )}

      {anyGraphBuilt && (
        <button 
          onClick={onAnalyze}
          className="w-full py-3 rounded-[9px] font-semibold text-xs flex items-center justify-center gap-1.5 bg-gradient-to-r from-[#059669] to-[#0d9488] text-white hover:opacity-90 transition-opacity"
        >
          <Se /> 모순 탐지 시작
        </button>
      )}
    </div>
  );
}
