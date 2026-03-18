import type { Project } from '../../types';
import { Gc } from '../common/Icons';

interface HeaderProps {
  activeProj: Project | undefined;
  isNew: boolean;
  stagedLength: number;
}

export default function Header({ activeProj, isNew, stagedLength }: HeaderProps) {
  return (
    <header className="h-[46px] border-b border-[rgba(63,63,70,0.15)] bg-[rgba(9,9,11,0.8)] backdrop-blur-md flex items-center justify-between px-5 shrink-0">
      <span className="text-[11px] text-[#52525b]">
        {isNew ? "새 프로젝트 생성" : activeProj?.name || ""}
      </span>
      <div className="flex items-center gap-1.5">
        {stagedLength > 0 && (
          <span className="text-[9px] text-[#34d399] flex items-center gap-0.5">
            <Gc /> {stagedLength}건 스테이징
          </span>
        )}
        <div className="pulse w-1.5 h-1.5 rounded-full bg-[#10b981]" />
      </div>
    </header>
  );
}
