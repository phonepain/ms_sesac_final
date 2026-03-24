import type { Project } from '../../types';

interface HeaderProps {
  activeProj: Project | undefined;
  isNew: boolean;
  stagedLength: number;
}

export default function Header({ activeProj, isNew, stagedLength }: HeaderProps) {
  return (
    <header className="h-12 border-b border-[#ede4d8] bg-[#fff8f0] flex items-center justify-between px-6 shrink-0">
      <span className="text-xs text-[#a89880]">
        {isNew ? "새 작품 분석" : activeProj?.name || ""}
      </span>
      <div className="flex items-center gap-2">
        {stagedLength > 0 && (
          <span className="text-[11px] text-[#2d7a56] font-semibold">
            ✅ {stagedLength}건 수정 대기 중
          </span>
        )}
        <div className="pulse w-1.5 h-1.5 rounded-full bg-[#2d7a56]" />
        <span className="text-[10px] text-[#a89880]">연결됨</span>
      </div>
    </header>
  );
}
