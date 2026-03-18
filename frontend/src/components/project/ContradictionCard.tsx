import { useState } from 'react';
import { Al, Cd, Cr, Qt, Ed, Gc } from '../common/Icons';
import { SV_COLORS } from '../../types';
import type { SeverityType } from '../../types';

export interface Contradiction {
  id: string;
  sv: SeverityType;
  tp: string;
  ch: string;
  ft: string;
  dl: string;
  ds: string;
  ev: Array<{ sr: string; lc: string; tx: string }>;
  cf: number;
  sg: string;
  al: string | null;
  ui: boolean;
  uq?: string;
  ot?: string;
}

interface ContradictionCardProps {
  item: Contradiction;
  isStaged?: boolean;
  onStage: (item: Contradiction & { fixedText: string }) => void;
}

export default function ContradictionCard({ item, isStaged = false, onStage }: ContradictionCardProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [fixedText, setFixedText] = useState(item.ot || '');
  const [userAnswer, setUserAnswer] = useState('');
  const [answered, setAnswered] = useState(false);

  const sv = SV_COLORS[item.sv] || SV_COLORS.info;

  return (
    <div 
      className="rounded-xl border transition-opacity duration-200"
      style={{
        borderColor: sv.bd,
        background: sv.bg,
        opacity: isStaged ? 0.45 : 1
      }}
    >
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-start gap-1.5 p-2.5 text-left text-inherit transition-colors hover:bg-black/10 rounded-xl"
      >
        <span 
          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-[3px] text-[8px] font-bold tracking-wider uppercase text-white shrink-0 mt-0.5"
          style={{ background: sv.bg2 }}
        >
          <Al /> {item.sv}
        </span>
        
        <div className="flex-1">
          <div className="flex items-center gap-1 flex-wrap mb-0.5">
            <span className="font-semibold text-[11px]" style={{ color: sv.tx }}>
              {item.ch}
            </span>
            <span className="text-[8px] bg-[rgba(39,39,42,0.4)] text-[#a1a1aa] px-1 py-0.5 rounded-sm">
              {item.tp}
            </span>
            {isStaged && (
              <span className="text-[7px] bg-[rgba(16,185,129,0.1)] text-[#34d399] px-1 py-0.5 rounded-sm">
                수정 대기
              </span>
            )}
          </div>
          <p className="text-[#a1a1aa] text-[10px] mt-0.5 italic">
            {item.dl}
          </p>
        </div>
        
        <div className="text-[#52525b] shrink-0 mt-1">
          {isOpen ? <Cd /> : <Cr />}
        </div>
      </button>

      {isOpen && (
        <div className="fade px-2.5 pb-2.5 flex flex-col gap-2">
          <div className="bg-[rgba(9,9,14,0.3)] rounded-md p-2">
            <div className="text-[9px] font-semibold text-[#71717a] mb-1">모순 설명</div>
            <p className="text-[#e4e4e7] text-[11px] leading-relaxed break-keep">
              {item.ds}
            </p>
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
            <p className="text-[#e4e4e7] text-[11px] leading-relaxed break-keep">
              {item.sg}
            </p>
          </div>

          {item.al && (
            <p className="text-[#52525b] text-[9px] italic break-keep">
              {item.al}
            </p>
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
              <span className="mono text-[#d4d4d8] text-[9px]">
                {Math.round(item.cf * 100)}%
              </span>
            </div>
          </div>

          {item.ui && (
            <div className="bg-[rgba(76,29,149,0.08)] border border-[rgba(139,92,246,0.1)] rounded-md p-2 mt-1">
              <div className="text-[9px] font-semibold text-[#a78bfa] mb-1">작가 확인 필요</div>
              <p className="text-[#e4e4e7] text-[10px] mb-1.5">{item.uq}</p>
              {answered ? (
                <span className="text-[10px] text-[#a78bfa]">답변: {userAnswer}</span>
              ) : (
                <div className="flex gap-1.5">
                  <input 
                    value={userAnswer}
                    onChange={e => setUserAnswer(e.target.value)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' && userAnswer.trim()) setAnswered(true);
                    }}
                    placeholder="의도 설명..."
                    className="flex-1 bg-[rgba(39,39,42,0.3)] border border-[rgba(63,63,70,0.15)] rounded text-[10px] text-[#e4e4e7] px-2 py-1 outline-none focus:border-[#a78bfa]/50"
                  />
                  <button 
                    onClick={() => { if (userAnswer.trim()) setAnswered(true); }}
                    className="px-2.5 py-1 bg-[#7c3aed] hover:bg-[#6d28d9] text-white rounded text-[10px] transition-colors"
                  >
                    전송
                  </button>
                </div>
              )}
            </div>
          )}

          {!isStaged && (
            <div className="border-t border-[rgba(63,63,70,0.06)] pt-2 mt-1.5">
              {isEditing ? (
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
                      onClick={() => setIsEditing(false)}
                      className="text-[9px] text-[#71717a] hover:text-white px-2 py-1 rounded border border-[rgba(63,63,70,0.2)] hover:bg-[#3f3f46]/50 transition-colors"
                    >
                      취소
                    </button>
                    <button 
                      onClick={() => {
                        onStage({ ...item, fixedText });
                        setIsEditing(false);
                      }}
                      className="flex items-center gap-1 text-[9px] font-semibold text-white bg-gradient-to-r from-[#059669] to-[#0d9488] hover:opacity-90 px-2.5 py-1 rounded shadow-sm shadow-[#10b981]/20 transition-all"
                    >
                      <Gc /> Commit
                    </button>
                  </div>
                </div>
              ) : (
                <button 
                  onClick={() => setIsEditing(true)}
                  className="flex items-center justify-center gap-1 w-full text-[10px] text-[#a1a1aa] hover:text-white py-1.5 rounded-md border border-[rgba(63,63,70,0.1)] hover:border-[#10b981]/30 hover:bg-[rgba(16,185,129,0.05)] transition-colors"
                >
                  <Ed /> 수정하여 스테이징
                </button>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
