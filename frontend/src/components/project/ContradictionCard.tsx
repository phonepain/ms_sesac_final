import { useState } from 'react';
import { Al, Cd, Cr, Qt, Gc, Rv } from '../common/Icons';
import { SV_COLORS } from '../../types';
import type { Contradiction, StagedFix, DecisionType } from '../../types';

interface ContradictionCardProps {
  item: Contradiction;
  isStaged: boolean;
  onStage: (fix: StagedFix) => void;
  onUnstageFix: (id: string) => void;
}

export default function ContradictionCard({ item, isStaged, onStage, onUnstageFix }: ContradictionCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [dec, setDec] = useState<DecisionType | null>(null);
  const [intentNote, setIntentNote] = useState('');
  const [intentSaved, setIntentSaved] = useState(false);
  const [fixedText, setFixedText] = useState(item.ot || '');

  const sv = SV_COLORS[item.sv] || SV_COLORS.info;

  const processed = (dec === 'intentional' && intentSaved) || (dec === 'fix' && isStaged) || dec === 'deferred';

  const handleUndo = () => {
    if (dec === 'fix' && isStaged) onUnstageFix(item.id);
    if (dec === 'intentional' && intentSaved) onUnstageFix(item.id);
    setDec(null);
    setIntentNote('');
    setIntentSaved(false);
    setFixedText(item.ot || '');
  };

  const headerBadge = (() => {
    if (dec === 'intentional' && intentSaved)
      return <span className="text-[7px] bg-[rgba(16,185,129,0.12)] text-[#34d399] px-1 py-0.5 rounded-sm">의도된 설정</span>;
    if (dec === 'fix' && !isStaged)
      return <span className="text-[7px] bg-[rgba(245,158,11,0.1)] text-[#fbbf24] px-1 py-0.5 rounded-sm">수정 중</span>;
    if (dec === 'fix' && isStaged)
      return <span className="text-[7px] bg-[rgba(16,185,129,0.1)] text-[#34d399] px-1 py-0.5 rounded-sm">수정 대기</span>;
    if (dec === 'deferred')
      return <span className="text-[7px] bg-[rgba(63,63,70,0.3)] text-[#71717a] px-1 py-0.5 rounded-sm">보류</span>;
    return (
      <span
        className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-[3px] text-[8px] font-bold tracking-wider uppercase text-white shrink-0"
        style={{ background: sv.bg2 }}
      >
        <Al /> {sv.l}
      </span>
    );
  })();

  return (
    <div
      className="rounded-xl border transition-all duration-200"
      style={{
        borderColor: processed ? 'rgba(63,63,70,0.15)' : sv.bd,
        background: processed ? 'rgba(39,39,42,0.05)' : sv.bg,
        opacity: processed ? 0.6 : 1
      }}
    >
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-start gap-1.5 p-2.5 text-left text-inherit transition-colors hover:bg-black/10 rounded-xl"
      >
        <div className="shrink-0 mt-0.5">{headerBadge}</div>

        <div className="flex-1">
          <div className="flex items-center gap-1 flex-wrap mb-0.5">
            <span className="font-semibold text-[11px]" style={{ color: processed ? '#52525b' : sv.tx }}>
              {item.ch}
            </span>
            <span className="text-[8px] bg-[rgba(39,39,42,0.4)] text-[#a1a1aa] px-1 py-0.5 rounded-sm">
              {item.tp}
            </span>
          </div>
          <p className="text-[#a1a1aa] text-[10px] mt-0.5 italic">{item.dl}</p>
        </div>

        <div className="text-[#52525b] shrink-0 mt-1">
          {isOpen ? <Cd /> : <Cr />}
        </div>
      </button>

      {isOpen && (
        <div className="fade px-2.5 pb-2.5 flex flex-col gap-2">
          <div className="bg-[rgba(9,9,14,0.3)] rounded-md p-2">
            <div className="text-[9px] font-semibold text-[#71717a] mb-1">모순 설명</div>
            <p className="text-[#e4e4e7] text-[11px] leading-relaxed break-keep">{item.ds}</p>
          </div>

          {item.ev.map((e, i) => (
            <div key={i} className="bg-[rgba(39,39,42,0.2)] rounded-md p-2 flex gap-1.5">
              <Qt />
              <div className="flex-1">
                <span className="mono text-[8px] text-[#34d399] tracking-tight">{e.sr}, {e.lc}</span>
                <p className="text-[10px] text-[#d4d4d8] mt-0.5 leading-snug">{e.tx}</p>
              </div>
            </div>
          ))}

          <div className="bg-[rgba(6,78,59,0.08)] rounded-md p-2 border border-[rgba(16,185,129,0.1)]">
            <div className="text-[9px] font-semibold text-[#34d399] mb-0.5">수정 제안</div>
            <p className="text-[#e4e4e7] text-[11px] leading-relaxed break-keep">{item.sg}</p>
          </div>

          {item.al && (
            <p className="text-[#52525b] text-[9px] italic break-keep">{item.al}</p>
          )}

          <div className="flex items-center justify-between mt-1">
            <span className="text-[9px] text-[#52525b]">확신도</span>
            <div className="flex items-center gap-1.5">
              <div className="w-[60px] h-[3px] bg-[#27272a] rounded-sm overflow-hidden">
                <div
                  className="h-full rounded-sm"
                  style={{
                    width: `${item.cf * 100}%`,
                    background: item.cf >= 0.8 ? '#f87171' : item.cf >= 0.6 ? '#fbbf24' : '#38bdf8'
                  }}
                />
              </div>
              <span className="mono text-[#d4d4d8] text-[9px]">{Math.round(item.cf * 100)}%</span>
            </div>
          </div>

          {/* Decision area */}
          <div className="border-t border-[rgba(63,63,70,0.06)] pt-2 mt-1.5">

            {/* No decision yet */}
            {dec === null && (
              <div className="flex gap-1.5 flex-wrap">
                <button
                  onClick={() => setDec('intentional')}
                  className="text-[9px] text-[#a78bfa] px-2 py-1 rounded-md border border-[rgba(139,92,246,0.2)] bg-[rgba(139,92,246,0.05)] hover:bg-[rgba(139,92,246,0.1)] transition-colors"
                >
                  의도된 설정
                </button>
                <button
                  onClick={() => setDec('fix')}
                  className="text-[9px] text-[#34d399] px-2 py-1 rounded-md border border-[rgba(16,185,129,0.2)] bg-[rgba(16,185,129,0.04)] hover:bg-[rgba(16,185,129,0.08)] transition-colors"
                >
                  모순 확인 → 수정
                </button>
                <button
                  onClick={() => setDec('deferred')}
                  className="text-[9px] text-[#71717a] px-2 py-1 rounded-md border border-[rgba(63,63,70,0.2)] hover:bg-[rgba(63,63,70,0.15)] transition-colors"
                >
                  보류
                </button>
              </div>
            )}

            {/* Intentional path */}
            {dec === 'intentional' && !intentSaved && (
              <div className="fade flex flex-col gap-1.5">
                <textarea
                  value={intentNote}
                  onChange={e => setIntentNote(e.target.value)}
                  rows={2}
                  placeholder="이유 메모 (선택 사항)..."
                  className="w-full bg-[rgba(39,39,42,0.3)] border border-[rgba(139,92,246,0.3)] rounded-md px-2 py-1.5 text-[11px] text-[#e4e4e7] outline-none resize-none focus:border-[#a78bfa]/50"
                />
                <div className="flex gap-1.5 justify-end">
                  <button
                    onClick={handleUndo}
                    className="flex items-center gap-0.5 text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.2)] hover:bg-[#3f3f46]/50 transition-colors"
                  >
                    <Rv /> 결정 취소
                  </button>
                  <button
                    onClick={() => {
                      onStage({ id: item.id, ch: item.ch, tp: item.tp, isIntentional: true, intentNote });
                      setIntentSaved(true);
                    }}
                    className="flex items-center gap-1 text-[9px] font-semibold text-white bg-gradient-to-r from-[#6d28d9] to-[#7c3aed] hover:opacity-90 px-2.5 py-1 rounded transition-all"
                  >
                    <Gc /> Commit
                  </button>
                </div>
              </div>
            )}

            {dec === 'intentional' && intentSaved && (
              <div className="fade flex items-center justify-between">
                <span className="text-[9px] text-[#34d399]">스테이징 완료</span>
                <button
                  onClick={handleUndo}
                  className="flex items-center gap-0.5 text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.2)] hover:bg-[#3f3f46]/50 transition-colors"
                >
                  <Rv /> 스테이징 취소
                </button>
              </div>
            )}

            {/* Fix path */}
            {dec === 'fix' && !isStaged && (
              <div className="fade">
                <textarea
                  value={fixedText}
                  onChange={e => setFixedText(e.target.value)}
                  rows={2}
                  className="w-full bg-[rgba(39,39,42,0.3)] border border-[rgba(16,185,129,0.3)] rounded-md px-2 py-1.5 text-[11px] text-[#e4e4e7] outline-none resize-none focus:border-[#10b981]/50"
                  placeholder="수정할 원고 내용을 입력하세요..."
                />
                <div className="flex gap-1.5 mt-1.5 justify-end">
                  <button
                    onClick={handleUndo}
                    className="flex items-center gap-0.5 text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.2)] hover:bg-[#3f3f46]/50 transition-colors"
                  >
                    <Rv /> 결정 취소
                  </button>
                  <button
                    onClick={() => onStage({ id: item.id, ch: item.ch, tp: item.tp, ot: item.ot, fixedText })}
                    className="flex items-center gap-1 text-[9px] font-semibold text-white bg-gradient-to-r from-[#059669] to-[#0d9488] hover:opacity-90 px-2.5 py-1 rounded shadow-sm shadow-[#10b981]/20 transition-all"
                  >
                    <Gc /> Commit
                  </button>
                </div>
              </div>
            )}

            {dec === 'fix' && isStaged && (
              <div className="fade flex items-center justify-between">
                <span className="text-[9px] text-[#34d399]">스테이징 완료</span>
                <button
                  onClick={handleUndo}
                  className="flex items-center gap-0.5 text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.2)] hover:bg-[#3f3f46]/50 transition-colors"
                >
                  <Rv /> 스테이징 취소
                </button>
              </div>
            )}

            {/* Deferred path */}
            {dec === 'deferred' && (
              <div className="fade flex items-center justify-between">
                <span className="text-[9px] text-[#71717a]">보류 처리됨</span>
                <button
                  onClick={handleUndo}
                  className="flex items-center gap-0.5 text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.2)] hover:bg-[#3f3f46]/50 transition-colors"
                >
                  <Rv /> 취소
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
