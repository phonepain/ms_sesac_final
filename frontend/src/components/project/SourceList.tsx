import { useRef } from 'react';
import { CAT_INFO } from '../../types';
import type { Project } from '../../types';
import { Db, Dw, Up2 } from '../common/Icons';

interface SourceListProps {
  sources: Project['sources'];
  onReupload?: (srcId: string, srcName: string, file: File) => void;
}

function SourceItem({
  s,
  onReupload
}: {
  s: Project['sources'][number];
  onReupload?: (srcId: string, srcName: string, file: File) => void;
}) {
  const fileInputRef = useRef<HTMLInputElement>(null);
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
    <div className="flex items-center gap-2 px-2 py-1.5 bg-[rgba(9,9,14,0.3)] rounded-md">
      <span className="text-xs">{c?.i || "📄"}</span>
      <div className="flex-1 min-w-0">
        <div className="text-[11px] text-[#e4e4e7] overflow-hidden text-ellipsis whitespace-nowrap">
          {s.n}
        </div>
        <div className="text-[9px] text-[#52525b]">
          {c?.l || '기타'} · 엔티티 {s.ent} · 사실 {s.fct}
        </div>
      </div>
      <div className="flex gap-1 shrink-0">
        <button
          onClick={handleDownload}
          className="text-[#52525b] hover:text-[#34d399] transition-colors p-0.5"
          title="다운로드"
        >
          <Dw />
        </button>
        <button
          onClick={() => fileInputRef.current?.click()}
          className="text-[#52525b] hover:text-[#34d399] transition-colors p-0.5"
          title="파일 업데이트"
        >
          <Up2 />
        </button>
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          accept=".txt,.pdf"
          onChange={e => {
            const file = e.target.files?.[0];
            if (file && onReupload) onReupload(s.id, s.n, file);
            e.target.value = '';
          }}
        />
      </div>
    </div>
  );
}

export default function SourceList({ sources, onReupload }: SourceListProps) {
  if (!sources || sources.length === 0) return null;

  return (
    <div className="bg-[rgba(39,39,42,0.1)] border border-[rgba(63,63,70,0.08)] rounded-[9px] p-3">
      <div className="text-[10px] font-bold text-[#71717a] mb-2 flex items-center gap-1">
        <Db />
        등록된 소스 <span className="mono text-[#52525b]">{sources.length}</span>
      </div>
      <div className="flex flex-col gap-1">
        {sources.map(s => (
          <SourceItem key={s.id} s={s} onReupload={onReupload} />
        ))}
      </div>
    </div>
  );
}
