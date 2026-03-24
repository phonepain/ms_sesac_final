import type { Project } from '../../types';

interface SidebarProps {
  projects: Project[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}

export default function Sidebar({ projects, activeId, onSelect, onNew }: SidebarProps) {
  return (
    <div className="w-[240px] border-r border-[#ede4d8] bg-[#fff8f0] flex flex-col h-screen shrink-0">
      {/* 로고 */}
      <div className="px-4 py-[18px] border-b border-[#ede4d8] flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-[#c4622d] flex items-center justify-center">
          <span className="text-white text-[13px] font-black serif">C</span>
        </div>
        <div>
          <div className="serif text-sm font-bold text-[#2c2416]">ContiCheck</div>
          <div className="text-[9px] text-[#a89880]">이야기 정합성 검사</div>
        </div>
      </div>

      {/* 새 작품 분석하기 */}
      <div className="px-3 py-3">
        <button
          onClick={onNew}
          className="w-full py-2.5 px-3 rounded-[10px] border border-dashed border-[#ede4d8] text-[#c4622d] text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors hover:bg-[#fdeee6] hover:border-[#c4622d]"
        >
          ＋ 새 작품 분석하기
        </button>
      </div>

      {/* 프로젝트 목록 */}
      <div className="flex-1 overflow-auto px-2 py-1">
        <div className="text-[9px] font-bold text-[#a89880] px-2 py-1.5 tracking-[0.06em]">내 작품</div>
        {projects.map(p => {
          const isAct = p.id === activeId;
          const cCnt = p.contradictions?.length || 0;
          return (
            <button
              key={p.id}
              onClick={() => onSelect(p.id)}
              className={`w-full text-left px-3 py-2.5 rounded-[10px] mb-0.5 transition-all duration-150 ${
                isAct
                  ? "bg-[#fdeee6] border border-[rgba(196,98,45,0.2)]"
                  : "bg-transparent border border-transparent hover:bg-[#f5efe6]"
              }`}
            >
              <div className={`text-xs mb-0.5 overflow-hidden text-ellipsis whitespace-nowrap ${
                isAct ? "font-bold text-[#c4622d]" : "font-medium text-[#2c2416]"
              }`}>
                {p.name}
              </div>
              <div className="flex items-center gap-1.5 text-[10px] text-[#a89880]">
                <span>{p.date}</span>
                {cCnt > 0 && <span className="text-[#b83232] font-semibold">⚠ {cCnt}건</span>}
                {cCnt === 0 && p.sources?.length > 0 && (
                  <span className="text-[#2d7a56]">✓ 이상 없음</span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
