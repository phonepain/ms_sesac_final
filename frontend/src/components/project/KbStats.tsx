import type { Project } from '../../types';

interface KbStatsProps {
  stats: Project['kb'];
}

export default function KbStats({ stats }: KbStatsProps) {
  const items = [
    { l: "등장인물", v: stats.characters, icon: "👥", c: "#c4622d" },
    { l: "주요 사실", v: stats.facts,      icon: "📝", c: "#c47c1a" },
    { l: "인물 관계", v: stats.relationships, icon: "🔗", c: "#2d7a56" },
    { l: "주요 사건", v: stats.events,     icon: "🎬", c: "#7c5cbf" },
    { l: "특성",      v: stats.traits,     icon: "✨", c: "#2d6a9f" },
  ];

  return (
    <div className="grid grid-cols-5 gap-2">
      {items.map(x => (
        <div
          key={x.l}
          className="bg-white border border-[#ede4d8] rounded-xl py-3 px-2 text-center"
          style={{ boxShadow: "0 2px 8px rgba(44,36,22,0.06)" }}
        >
          <div className="text-xl mb-1">{x.icon}</div>
          <div className="text-[22px] font-bold serif" style={{ color: x.c }}>{x.v}</div>
          <div className="text-[#a89880] text-[10px] mt-0.5">{x.l}</div>
        </div>
      ))}
    </div>
  );
}
