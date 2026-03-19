import type { Project } from '../../types';
import { Pl } from '../common/Icons';

interface SidebarProps {
  projects: Project[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function Sidebar({ projects, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <div className="w-[260px] border-r border-[rgba(63,63,70,0.2)] bg-[rgba(9,9,14,0.6)] flex flex-col h-screen shrink-0">
      {/* 로고 */}
      <div className="px-4 py-3.5 border-b border-[rgba(63,63,70,0.15)] flex items-center gap-2">
        <div className="w-[22px] h-[22px] rounded md bg-gradient-to-br from-[#10b981] to-[#0d9488] flex items-center justify-center">
          <span className="text-white text-[8px] font-black">C</span>
        </div>
        <span className="text-white font-bold text-[13px]">ContiCheck</span>
        <span className="mono text-[8px] bg-[#27272a] text-[#52525b] px-1 py-0.5 rounded-[3px]">v3</span>
      </div>
      
      {/* 새 프로젝트 */}
      <div className="px-3 py-2.5">
        <button 
          onClick={onNew} 
          className="w-full py-2.5 px-3 rounded-lg border border-dashed border-[rgba(16,185,129,0.3)] bg-[rgba(16,185,129,0.04)] text-[#34d399] text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors hover:bg-[rgba(16,185,129,0.1)]"
        >
          <Pl /> 새 프로젝트
        </button>
      </div>
      
      {/* 프로젝트 목록 */}
      <div className="flex-1 overflow-auto px-2 py-1">
        {projects.map(p => {
          const isAct = p.id === activeId;
          const cCnt = p.contradictions?.length || 0;
          return (
            <button 
              key={p.id} 
              onClick={() => onSelect(p.id)} 
              className={`w-full text-left px-3 py-2.5 rounded-lg mb-1 transition-all duration-150 ${
                isAct 
                  ? "bg-[rgba(16,185,129,0.08)] border border-[rgba(16,185,129,0.15)]" 
                  : "bg-transparent border border-transparent hover:bg-[rgba(39,39,42,0.5)]"
              }`}
            >
              <div className={`text-xs mb-1 overflow-hidden text-ellipsis whitespace-nowrap ${
                isAct ? "font-semibold text-white" : "font-medium text-[#a1a1aa]"
              }`}>
                {p.name}
              </div>
              <div className="flex items-center gap-1.5 text-[9px] text-[#52525b]">
                <span>{p.date}</span>
                <span className="text-[#34d399]">{p.kb.characters}명</span>
                <span className="text-[#38bdf8]">{p.kb.facts}사실</span>
                {cCnt > 0 && <span className="text-[#f87171]">{cCnt}모순</span>}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
