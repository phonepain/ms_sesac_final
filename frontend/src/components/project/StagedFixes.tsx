import { Gc, Gp } from '../common/Icons';

interface StagedFix {
  id: string;
  ot?: string; // original text
  fixedText?: string;
}

interface StagedFixesProps {
  staged: StagedFix[];
  onRemove: (id: string) => void;
  onPush: () => void;
  onClear: () => void;
}

export default function StagedFixes({ staged, onRemove, onPush, onClear }: StagedFixesProps) {
  if (staged.length === 0) return null;

  return (
    <div className="fade bg-[rgba(16,185,129,0.03)] border border-[rgba(16,185,129,0.12)] rounded-xl p-3 mb-3">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5">
          <div className="text-[#34d399]"><Gc /></div>
          <span className="text-[#34d399] text-[11px] font-bold">스테이징</span>
          <span className="mono text-[9px] bg-[rgba(16,185,129,0.1)] text-[#34d399] px-1.5 py-0.5 rounded-sm">
            {staged.length}
          </span>
        </div>
        <div className="flex gap-1.5">
          <button 
            onClick={onClear}
            className="text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.12)] hover:bg-[rgba(63,63,70,0.2)] transition-colors"
          >
            취소
          </button>
          <button 
            onClick={onPush}
            className="flex items-center gap-1 text-[10px] font-semibold text-white bg-gradient-to-br from-[#059669] to-[#0f766e] px-2.5 py-1 rounded-md shadow-sm shadow-[#10b981]/20 hover:opacity-90 transition-opacity"
          >
            <Gp /> Push
          </button>
        </div>
      </div>
      
      <div className="flex flex-col gap-1">
        {staged.map(s => (
          <div key={s.id} className="bg-[rgba(9,9,14,0.25)] rounded-md px-2 py-1.5 text-[10px] group relative">
            <button 
              onClick={() => onRemove(s.id)}
              className="absolute top-1.5 right-1.5 text-[#52525b] hover:text-[#ef4444] opacity-0 group-hover:opacity-100 transition-opacity"
              title="스테이징 취소"
            >
              ×
            </button>
            <div className="leading-relaxed pr-4">
              <span className="text-[#ef4444] mr-1">-</span>
              <span className="text-[#71717a] line-through decoration-[#ef4444]/30">
                {s.ot?.slice(0, 40) || '원문 없음'}...
              </span>
              <br/>
              <span className="text-[#34d399] mr-1">+</span>
              <span className="text-[#d4d4d8]">
                {s.fixedText?.slice(0, 40)}...
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
