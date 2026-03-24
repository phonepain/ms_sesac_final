import type { Project } from '../../types';

interface HeaderProps {
  activeProj: Project | undefined;
  isNew: boolean;
  stagedLength: number;
  onToggleSidebar: () => void;
}

export default function Header({ activeProj, isNew, stagedLength, onToggleSidebar }: HeaderProps) {
  return (
    <header className="h-12 border-b border-[#ede4d8] bg-[#fff8f0] flex items-center justify-between px-4 md:px-6 shrink-0">
      <div className="flex items-center gap-2">
        {/* 모바일 햄버거 버튼 */}
        <button
          onClick={onToggleSidebar}
          className="md:hidden flex flex-col justify-center gap-[4px] w-7 h-7 shrink-0"
          aria-label="메뉴 열기"
        >
          <span className="block h-[2px] w-5 bg-[#a89880] rounded-sm" />
          <span className="block h-[2px] w-5 bg-[#a89880] rounded-sm" />
          <span className="block h-[2px] w-5 bg-[#a89880] rounded-sm" />
        </button>
        <span className="text-xs text-[#a89880] truncate max-w-[160px] md:max-w-none">
          {isNew ? "새 작품 분석" : activeProj?.name || ""}
        </span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {stagedLength > 0 && (
          <span className="text-[11px] text-[#2d7a56] font-semibold hidden sm:inline">
            ✅ {stagedLength}건 수정 대기 중
          </span>
        )}
        {stagedLength > 0 && (
          <span className="text-[11px] text-[#2d7a56] font-semibold sm:hidden">
            ✅ {stagedLength}건
          </span>
        )}
        <div className="pulse w-1.5 h-1.5 rounded-full bg-[#2d7a56]" />
        <span className="text-[10px] text-[#a89880]">연결됨</span>
      </div>
    </header>
  );
}
