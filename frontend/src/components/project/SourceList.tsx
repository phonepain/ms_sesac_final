import { CAT_INFO } from '../../types';
import type { Project } from '../../types';
import { Db } from '../common/Icons';

interface SourceListProps {
  sources: Project['sources'];
}

export default function SourceList({ sources }: SourceListProps) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="bg-[rgba(39,39,42,0.1)] border border-[rgba(63,63,70,0.08)] rounded-[9px] p-3">
      <div className="text-[10px] font-bold text-[#71717a] mb-2 flex items-center gap-1">
        <Db /> 
        등록된 소스 <span className="mono text-[#52525b]">{sources.length}</span>
      </div>
      <div className="flex flex-col gap-1">
        {sources.map(s => {
          const c = CAT_INFO[s.cat];
          return (
            <div key={s.id} className="flex items-center gap-2 px-2 py-1.5 bg-[rgba(9,9,14,0.3)] rounded-md">
              <span className="text-xs">{c?.i || "📄"}</span>
              <div className="flex-1 min-w-0">
                <div className="text-[11px] text-[#e4e4e7] overflow-hidden text-ellipsis whitespace-nowrap">
                  {s.n}
                </div>
                <div className="text-[9px] text-[#52525b]">
                  {c?.l || '기타'} · 엔티티 {s.ent} · 사실 {s.fct}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
