import { XIcon, In } from './Icons';

interface OnboardingProps {
  onClose: () => void;
}

export default function Onboarding({ onClose }: OnboardingProps) {
  const modes = [
    { m: "시나리오만", it: ["🎬"], q: "기본", c: "#71717a" },
    { m: "세계관+설정집", it: ["🌍","📋"], q: "설정 검증", c: "#a78bfa" },
    { m: "전체 (권장)", it: ["🌍","📋","🎬"], q: "최고 품질", c: "#34d399" }
  ];

  return (
    <div className="fade relative bg-gradient-to-br from-[rgba(16,185,129,0.04)] to-[rgba(139,92,246,0.04)] border border-[rgba(16,185,129,0.12)] rounded-xl p-4 mb-4">
      <button 
        onClick={onClose}
        className="absolute top-2 right-2 text-[#52525b] hover:text-white p-1 rounded transition-colors"
      >
        <XIcon />
      </button>
      
      <h3 className="text-white text-[13px] font-bold mb-2">👋 사용 가이드</h3>
      
      <div className="grid grid-cols-3 gap-2 mb-2">
        {modes.map(x => (
          <div key={x.m} className="bg-[rgba(9,9,14,0.4)] border border-[rgba(63,63,70,0.1)] rounded-lg p-2.5 px-3">
            <div className="text-[8px] font-bold mb-[1px]" style={{ color: x.c }}>{x.q}</div>
            <div className="text-[10px] font-semibold text-[#e4e4e7] mb-1">{x.m}</div>
            <div className="flex gap-[3px]">
              {x.it.map(i => <span key={i} className="text-[13px]">{i}</span>)}
            </div>
          </div>
        ))}
      </div>
      
      <p className="text-[9px] text-[#52525b] flex items-center gap-1 font-medium mt-1">
        <In /> 세계관+설정집을 함께 등록하면 더 정확합니다.
      </p>
    </div>
  );
}
