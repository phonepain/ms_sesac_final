import { Ld, Ck } from './Icons';

export interface ProgressStep {
  l: string; // label
  ms: number; // mock time in ms
}

interface ProgressOverlayProps {
  step: number;
  steps: ProgressStep[];
  title: string;
}

export default function ProgressOverlay({ step, steps, title }: ProgressOverlayProps) {
  return (
    <div className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50 flex items-center justify-center">
      <div className="bg-[#18181b] border border-[rgba(63,63,70,0.4)] rounded-xl p-6 max-w-[370px] w-full mx-4">
        
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-[30px] h-[30px] rounded-lg bg-[rgba(16,185,129,0.1)] border border-[rgba(16,185,129,0.2)] flex items-center justify-center text-[#10b981]">
            <Ld />
          </div>
          <div className="text-white font-semibold text-sm">{title}</div>
        </div>

        <div className="flex flex-col gap-1.5">
          {steps.map((s, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className={`w-[18px] h-[18px] rounded-full flex items-center justify-center text-[8px] ${
                i < step 
                  ? "bg-[#10b981] text-white" 
                  : i === step 
                    ? "bg-[rgba(16,185,129,0.2)] border border-[#10b981] text-[#34d399]" 
                    : "bg-[#27272a] border border-[#3f3f46] text-[#52525b]"
              }`}>
                {i < step ? <Ck /> : i + 1}
              </div>
              <span className={`text-[11px] ${
                i < step ? "text-[#a1a1aa]" : i === step ? "text-white" : "text-[#52525b]"
              }`}>
                {s.l}
              </span>
            </div>
          ))}
        </div>

        <div className="mt-3 h-[3px] bg-[#27272a] rounded-sm overflow-hidden">
          <div 
            className="h-full bg-gradient-to-r from-[#10b981] to-[#2dd4bf] rounded-sm transition-all duration-500 ease-out" 
            style={{ width: `${((step + 1) / steps.length) * 100}%` }} 
          />
        </div>

      </div>
    </div>
  );
}
