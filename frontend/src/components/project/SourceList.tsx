import { CAT_INFO } from '../../types';
import type { Project } from '../../types';

interface SourceListProps {
  sources: Project['sources'];
}

function SourceItem({
  s,
}: {
  s: Project['sources'][number];
}) {
  const c = CAT_INFO[s.cat];

  const handleDownload = async () => {
    try {
      const res = await fetch(`/api/sources/${s.id}/download`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = s.n;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="flex items-center gap-2.5 px-2.5 py-2 bg-[#f5efe6] rounded-lg mb-1">
      <span className="text-base">{c?.i || "📄"}</span>
      <div className="flex-1 min-w-0">
        <div className="text-xs font-medium text-[#2c2416] overflow-hidden text-ellipsis whitespace-nowrap">
          {s.n}
        </div>
        <div className="text-[10px] text-[#a89880]">
          {c?.l || '기타'} · 인물 {s.ent}명 · 사실 {s.fct}건
        </div>
      </div>
      <div className="flex gap-1.5 shrink-0">
        <button
          onClick={handleDownload}
          title="원본 다운로드"
          className="text-[10px] text-[#a89880] hover:text-[#c4622d] px-2 py-1 rounded border border-[#ede4d8] bg-white transition-colors"
        >
          ↓
        </button>
      </div>
      <span className="text-[10px] text-[#2d7a56] font-semibold shrink-0">✓ 완료</span>
    </div>
  );
}

export default function SourceList({ sources }: SourceListProps) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="bg-white border border-[#ede4d8] rounded-xl p-4" style={{ boxShadow: "0 2px 8px rgba(44,36,22,0.06)" }}>
      <div className="text-xs font-semibold text-[#2c2416] mb-3">📂 등록된 파일</div>
      <div className="flex flex-col">
        {sources.map(s => (
          <SourceItem key={s.id} s={s} />
        ))}
      </div>
    </div>
  );
}
