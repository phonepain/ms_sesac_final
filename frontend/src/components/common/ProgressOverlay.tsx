export interface ProgressStep {
  l: string;
  ms: number;
}

interface ProgressOverlayProps {
  step: number;
  steps: ProgressStep[];
  title: string;
}

export default function ProgressOverlay({ step, steps, title }: ProgressOverlayProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(253,250,245,0.9)", backdropFilter: "blur(6px)" }}>
      <div
        className="bg-white border border-[#ede4d8] rounded-2xl p-8 max-w-[360px] w-[90%]"
        style={{ boxShadow: "0 8px 32px rgba(44,36,22,0.12)" }}
      >
        {/* 스피너 + 제목 */}
        <div className="text-center mb-6">
          <div
            className="w-12 h-12 rounded-full bg-[#fdeee6] border-2 border-[#c4622d] flex items-center justify-center mx-auto mb-3 spin text-[#c4622d] text-xl"
          >
            ⟳
          </div>
          <h3 className="serif text-[15px] font-bold text-[#2c2416]">{title}</h3>
        </div>

        {/* 단계 목록 */}
        <div className="flex flex-col gap-2">
          {steps.map((s, i) => (
            <div key={i} className="flex items-center gap-2.5">
              <div className={`w-[22px] h-[22px] rounded-full flex-shrink-0 flex items-center justify-center text-[11px] font-bold ${
                i < step
                  ? "bg-[#2d7a56] text-white"
                  : i === step
                    ? "bg-[#fdeee6] border-2 border-[#c4622d] text-[#c4622d]"
                    : "bg-[#f5efe6] text-[#a89880]"
              }`}>
                {i < step ? "✓" : i + 1}
              </div>
              <span className={`text-[12px] ${
                i < step ? "text-[#a89880]" : i === step ? "text-[#2c2416] font-semibold" : "text-[#a89880]"
              }`}>
                {s.l}
              </span>
            </div>
          ))}
        </div>

        {/* 진행 바 */}
        <div className="mt-5 h-1 bg-[#f5efe6] rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all duration-500"
            style={{
              width: `${((step + 1) / steps.length) * 100}%`,
              background: "linear-gradient(90deg, #c4622d, #e8905e)"
            }}
          />
        </div>
      </div>
    </div>
  );
}
