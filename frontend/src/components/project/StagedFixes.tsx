import type { StagedFix } from '../../types';

interface StagedFixesProps {
  staged: StagedFix[];
  onRemove: (id: string) => void;
  onPush: () => void;
  onClear: () => void;
}

export default function StagedFixes({ staged, onRemove, onPush, onClear }: StagedFixesProps) {
  if (staged.length === 0) return null;

  return (
    <div className="fade bg-[#e8f4ee] border border-[rgba(45,122,86,0.2)] rounded-xl p-3.5 mb-1">
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-1.5">
          <span className="text-[13px] font-bold text-[#2d7a56]">✅ 수정 대기 중</span>
          <span className="text-[11px] bg-[#2d7a56] text-white px-2 py-0.5 rounded-full font-bold">
            {staged.length}건
          </span>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={onClear}
            className="text-[11px] text-[#a89880] px-2.5 py-1 rounded-md border border-[#ede4d8] bg-white hover:bg-[#f5efe6] transition-colors"
          >
            취소
          </button>
          <button
            onClick={onPush}
            className="text-[11px] font-bold text-white bg-[#2d7a56] px-3.5 py-1 rounded-md hover:bg-[#255f44] transition-colors"
          >
            📤 원고에 반영하기
          </button>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        {staged.map(s => (
          <div key={s.id} className="bg-white/60 rounded-lg px-2.5 py-2 text-[11px] relative group">
            <button
              onClick={() => onRemove(s.id)}
              className="absolute top-1.5 right-2 text-[#a89880] hover:text-[#b83232] opacity-0 group-hover:opacity-100 transition-opacity"
              title="스테이징 취소"
            >
              ✕
            </button>
            {s.isIntentional ? (
              <>
                <span className="inline-block text-[9px] font-bold bg-[rgba(124,92,191,0.1)] text-[#7c5cbf] px-1.5 py-0.5 rounded mr-1.5">의도된 설정</span>
                <span className="text-[#6b5c47]">{s.ch} · {s.tp}</span>
                {s.intentNote && <div className="text-[#a89880] mt-0.5 italic">메모: "{s.intentNote}"</div>}
              </>
            ) : (
              <>
                <span className="text-[#b83232]">수정 전: </span>
                <span className="text-[#a89880]">{(s.ot || '').slice(0, 50)}...</span>
                <br />
                <span className="text-[#2d7a56]">수정 후: </span>
                <span className="text-[#2c2416]">{(s.fixedText || '').slice(0, 50)}...</span>
              </>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
