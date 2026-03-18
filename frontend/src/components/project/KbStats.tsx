import type { Project } from '../../types';
import { Gr, Db, Ln, Zp, Ed } from '../common/Icons';

interface KbStatsProps {
  stats: Project['kb'];
}

export default function KbStats({ stats }: KbStatsProps) {
  const items = [
    { l: "캐릭터", v: stats.characters, c: "#34d399", ic: <Gr /> },
    { l: "사실", v: stats.facts, c: "#38bdf8", ic: <Db /> },
    { l: "관계", v: stats.relationships, c: "#fbbf24", ic: <Ln /> },
    { l: "이벤트", v: stats.events, c: "#fb7185", ic: <Zp /> },
    { l: "특성", v: stats.traits, c: "#a78bfa", ic: <Ed /> }
  ];

  return (
    <div className="grid grid-cols-5 gap-1.5">
      {items.map(x => (
        <div 
          key={x.l} 
          className="bg-[rgba(39,39,42,0.2)] border border-[rgba(63,63,70,0.1)] rounded-lg p-2.5 text-center"
        >
          <div className="opacity-70 mb-[1px] flex justify-center" style={{ color: x.c }}>
            {x.ic}
          </div>
          <div className="mono text-lg font-bold" style={{ color: x.c }}>
            {x.v}
          </div>
          <div className="text-[#52525b] text-[9px]">
            {x.l}
          </div>
        </div>
      ))}
    </div>
  );
}
