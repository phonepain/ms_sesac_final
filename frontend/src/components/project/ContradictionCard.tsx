import { useState } from 'react';
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

  // Fallback: sv가 없으면 info로 대체
  const sv = SV_COLORS[item?.sv] ?? SV_COLORS.info;
  const processed = (dec === 'intentional' && intentSaved) || (dec === 'fix' && isStaged) || dec === 'deferred';

  const handleUndo = () => {
    if (dec === 'fix' && isStaged) onUnstageFix(item.id);
    if (dec === 'intentional' && intentSaved) onUnstageFix(item.id);
    setDec(null);
    setIntentNote('');
    setIntentSaved(false);
    setFixedText(item.ot || '');
  };

  // 데이터 없을 때 fallback
  const charName   = item.ch  || '(캐릭터 미상)';
  const typeLabel  = item.tp  || '';
  const dialogue   = item.dl  || '';
  const desc       = item.ds  || '(설명 없음)';
  const suggestion = item.sg  || '';
  const alt        = item.al  || '';
  const origText   = item.ot  || '';
  const evidence   = Array.isArray(item.ev) ? item.ev : [];
  const confidence = typeof item.cf === 'number' ? item.cf : 0;

  const statusBadge = (() => {
    if (dec === 'intentional' && intentSaved)
      return <span className="text-[10px] bg-[rgba(45,122,86,0.1)] text-[#2d7a56] px-2 py-0.5 rounded-md font-semibold">✓ 의도된 설정으로 저장</span>;
    if (dec === 'fix' && !isStaged)
      return <span className="text-[10px] bg-[#fef3db] text-[#c47c1a] px-2 py-0.5 rounded-md font-semibold">✏️ 수정 중</span>;
    if (dec === 'fix' && isStaged)
      return <span className="text-[10px] bg-[#e8f4ee] text-[#2d7a56] px-2 py-0.5 rounded-md font-semibold">✅ 수정 저장됨</span>;
    if (dec === 'deferred')
      return <span className="text-[10px] bg-[#f5efe6] text-[#a89880] px-2 py-0.5 rounded-md">보류</span>;
    return (
      <span
        className="inline-block text-[10px] font-bold px-2 py-0.5 rounded-md text-white"
        style={{ background: sv.bg2, flexShrink: 0 }}
      >
        {sv.emoji} {sv.l}
      </span>
    );
  })();

  return (
    /*
     * [Layout Fix]
     * - flex-shrink: 0  → 부모 flex 컨테이너가 카드를 압축하지 못하도록 방지
     * - width: 100%     → 컬럼 너비를 꽉 채움
     * - min-height: 48px → 빈 데이터여도 최소 높이 확보
     * - overflow: visible (overflow-hidden 제거) → 높이 0 상태에서 내용 잘림 방지
     */
    <div
      className="rounded-2xl border transition-all duration-200"
      style={{
        flexShrink: 0,          /* ← 핵심: flex 압축 방지 */
        width: '100%',
        minHeight: 48,
        borderColor: processed ? '#ede4d8' : sv.bd,
        background:  processed ? '#fdfaf5' : sv.bg,
        opacity: processed ? 0.65 : 1,
        /* overflow: visible (기본값 유지 — hidden 쓰지 않음) */
      }}
    >
      {/* ── 헤더 버튼 ── */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-start gap-2.5 px-4 py-3.5 text-left hover:brightness-95 transition-all rounded-2xl"
        style={{ minHeight: 48 }}  /* 버튼 자체도 최소 높이 보장 */
      >
        <div style={{ flexShrink: 0, marginTop: 2 }}>{statusBadge}</div>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div className="flex items-center gap-1.5 flex-wrap mb-1">
            <span className="font-semibold text-[13px]" style={{ color: processed ? '#a89880' : '#2c2416' }}>
              {charName}
            </span>
            {typeLabel && (
              <span className="text-[10px] bg-white/60 text-[#6b5c47] px-1.5 py-0.5 rounded border border-[#ede4d8]">
                {typeLabel}
              </span>
            )}
          </div>
          {dialogue && (
            <p className="text-[#6b5c47] text-[12px] italic leading-snug"
               style={{ wordBreak: 'break-word' }}>
              {dialogue}
            </p>
          )}
          {isStaged && !processed && (
            <span className="text-[10px] text-[#2d7a56] font-semibold mt-1 block">✅ 수정 대기 중</span>
          )}
        </div>

        <span className="text-[#a89880] text-sm" style={{ flexShrink: 0, marginTop: 2 }}>
          {isOpen ? '▲' : '▼'}
        </span>
      </button>

      {/* ── 펼쳐진 상세 내용 ── */}
      {isOpen && (
        <div
          className="fade px-4 pb-4 flex flex-col gap-3"
          style={{
            /* height: auto (명시적으로 고정 height/max-height 없음) */
            minHeight: 100,
          }}
        >
          {/* 문제의 대사/장면 */}
          {dialogue && (
            <div className="bg-white/60 rounded-xl p-3" style={{ borderLeft: `3px solid ${sv.bg2}` }}>
              <div className="text-[10px] font-semibold text-[#a89880] mb-1.5">📣 문제의 대사·장면</div>
              <p className="text-[13px] italic text-[#2c2416] leading-relaxed" style={{ wordBreak: 'break-word' }}>
                "{dialogue}"
              </p>
            </div>
          )}

          {/* 왜 모순인가 */}
          <div>
            <div className="text-[10px] font-semibold text-[#a89880] mb-1.5">🔍 왜 모순인가요?</div>
            <p className="text-[12px] text-[#6b5c47] leading-[1.8]" style={{ wordBreak: 'break-word' }}>
              {desc}
            </p>
          </div>

          {/* 근거 */}
          {evidence.length > 0 ? (
            evidence.map((e, i) => (
              <div key={i} className="bg-white/50 rounded-lg px-3 py-2">
                <div className="text-[10px] text-[#c4622d] font-semibold mb-1">
                  📄 {e.sr || '출처 미상'}{e.lc ? ` — ${e.lc}` : ''}
                </div>
                <p className="text-[11px] text-[#6b5c47] leading-snug" style={{ wordBreak: 'break-word' }}>
                  {e.tx || '(내용 없음)'}
                </p>
              </div>
            ))
          ) : (
            <div className="text-[10px] text-[#a89880] italic">근거 데이터 없음</div>
          )}

          {/* 수정 제안 */}
          {suggestion ? (
            <div className="bg-[#e8f4ee] border border-[rgba(45,122,86,0.15)] rounded-xl p-3">
              <div className="text-[10px] font-semibold text-[#2d7a56] mb-1.5">✏️ 수정 제안</div>
              <p className="text-[12px] text-[#2c2416] leading-relaxed" style={{ wordBreak: 'break-word' }}>
                {suggestion}
              </p>
            </div>
          ) : null}

          {/* 대안 해석 */}
          {alt && (
            <p className="text-[11px] text-[#a89880] italic" style={{ wordBreak: 'break-word' }}>
              💡 {alt}
            </p>
          )}

          {/* 확신도 */}
          {confidence > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-[10px] text-[#a89880]" style={{ flexShrink: 0 }}>분석 확신도</span>
              <div className="flex-1 h-1.5 bg-[#ede4d8] rounded-full overflow-hidden" style={{ minWidth: 60 }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${confidence * 100}%`,
                    background: confidence >= 0.8 ? '#b83232' : confidence >= 0.6 ? '#c47c1a' : '#2d7a56',
                  }}
                />
              </div>
              <span className="mono text-[10px] text-[#6b5c47] font-semibold" style={{ flexShrink: 0 }}>
                {Math.round(confidence * 100)}%
              </span>
            </div>
          )}

          {/* ── 처리 영역 ── */}
          <div className="border-t border-[rgba(44,36,22,0.06)] pt-3">

            {/* 미결정 — 3가지 선택 */}
            {dec === null && (
              <div className="flex gap-2 flex-wrap">
                <button
                  onClick={() => setDec('intentional')}
                  className="flex-1 py-2.5 px-3 rounded-lg border border-[rgba(124,92,191,0.25)] bg-[rgba(124,92,191,0.06)] text-[#7c5cbf] text-[11px] font-semibold hover:bg-[rgba(124,92,191,0.12)] transition-colors"
                  style={{ minWidth: 80 }}
                >
                  💡 의도된 설정
                </button>
                <button
                  onClick={() => setDec('fix')}
                  className="flex-1 py-2.5 px-3 rounded-lg border border-[#ede4d8] bg-white text-[#6b5c47] text-[11px] font-semibold hover:border-[#c4622d] hover:text-[#c4622d] transition-colors"
                  style={{ minWidth: 80 }}
                >
                  ✏️ 직접 수정하기
                </button>
                <button
                  onClick={() => setDec('deferred')}
                  className="px-3 py-2.5 rounded-lg border border-[#ede4d8] bg-white text-[#a89880] text-[11px] hover:bg-[#f5efe6] transition-colors"
                >
                  보류
                </button>
              </div>
            )}

            {/* 의도된 설정 — 메모 입력 */}
            {dec === 'intentional' && !intentSaved && (
              <div className="fade flex flex-col gap-2">
                <div className="text-[10px] font-semibold text-[#a89880]">
                  💬 이 부분이 의도된 이유를 알려주세요 (선택)
                </div>
                <textarea
                  value={intentNote}
                  onChange={e => setIntentNote(e.target.value)}
                  rows={2}
                  placeholder="예: 회상 장면, 복선, 캐릭터의 의도적 거짓말..."
                  className="w-full bg-white border border-[#ede4d8] rounded-lg px-3 py-2 text-[12px] text-[#2c2416] outline-none resize-none focus:border-[#7c5cbf]"
                  style={{ minHeight: 56 }}
                />
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={handleUndo}
                    className="text-[11px] text-[#a89880] px-3 py-1.5 rounded-lg border border-[#ede4d8] bg-white hover:bg-[#f5efe6] transition-colors"
                  >
                    취소
                  </button>
                  <button
                    onClick={() => {
                      onStage({ id: item.id, ch: charName, tp: typeLabel, isIntentional: true, intentNote });
                      setIntentSaved(true);
                    }}
                    className="text-[11px] font-bold text-white bg-[#7c5cbf] px-4 py-1.5 rounded-lg hover:bg-[#6a4da8] transition-colors"
                  >
                    저장하기
                  </button>
                </div>
              </div>
            )}

            {dec === 'intentional' && intentSaved && (
              <div className="fade flex items-center justify-between">
                <span className="text-[11px] text-[#2d7a56]">✅ 의도된 설정으로 저장됨</span>
                <button
                  onClick={handleUndo}
                  className="text-[10px] text-[#a89880] px-2.5 py-1 rounded border border-[#ede4d8] bg-white hover:bg-[#f5efe6] transition-colors"
                >
                  취소
                </button>
              </div>
            )}

            {/* 수정 모드 */}
            {dec === 'fix' && !isStaged && (
              <div className="fade flex flex-col gap-2">
                <div className="text-[10px] font-semibold text-[#a89880]">✍️ 수정할 내용을 입력하세요</div>
                <textarea
                  value={fixedText}
                  onChange={e => setFixedText(e.target.value)}
                  rows={3}
                  className="w-full bg-white border border-[#ede4d8] rounded-lg px-3 py-2 text-[12px] text-[#2c2416] outline-none resize-none focus:border-[#c4622d] leading-relaxed"
                  style={{ minHeight: 72 }}
                />
                <div className="flex gap-2 justify-end">
                  <button
                    onClick={handleUndo}
                    className="text-[11px] text-[#a89880] px-3 py-1.5 rounded-lg border border-[#ede4d8] bg-white hover:bg-[#f5efe6] transition-colors"
                  >
                    취소
                  </button>
                  <button
                    onClick={() => onStage({ id: item.id, ch: charName, tp: typeLabel, ot: origText, fixedText })}
                    className="text-[11px] font-bold text-white bg-[#2d7a56] px-4 py-1.5 rounded-lg hover:bg-[#255f44] transition-colors"
                  >
                    ✓ 수정 저장하기
                  </button>
                </div>
              </div>
            )}

            {dec === 'fix' && isStaged && (
              <div className="fade flex items-center justify-between">
                <span className="text-[11px] text-[#2d7a56]">✅ 수정 대기 중</span>
                <button
                  onClick={handleUndo}
                  className="text-[10px] text-[#a89880] px-2.5 py-1 rounded border border-[#ede4d8] bg-white hover:bg-[#f5efe6] transition-colors"
                >
                  취소
                </button>
              </div>
            )}

            {/* 보류 */}
            {dec === 'deferred' && (
              <div className="fade flex items-center justify-between bg-[#f5efe6] rounded-lg px-3 py-2">
                <span className="text-[11px] text-[#a89880]">보류 처리됨</span>
                <button
                  onClick={handleUndo}
                  className="text-[10px] text-[#a89880] px-2.5 py-1 rounded border border-[#ede4d8] bg-white hover:bg-[#f5efe6] transition-colors"
                >
                  취소
                </button>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
