import { useState, useRef, useEffect } from 'react';
import type { Project } from '../../types';

interface SidebarProps {
  projects: Project[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onResetAll: () => void;
  onRenameProject: (id: string, name: string) => void;
}

export default function Sidebar({ projects, activeId, onSelect, onNew, onResetAll, onRenameProject }: SidebarProps) {
  const [showConfirm, setShowConfirm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editingId) inputRef.current?.focus();
  }, [editingId]);

  const startEdit = (e: React.MouseEvent, p: Project) => {
    e.stopPropagation();
    setEditingId(p.id);
    setEditingName(p.name);
  };

  const commitEdit = () => {
    if (editingId && editingName.trim()) {
      onRenameProject(editingId, editingName.trim());
    }
    setEditingId(null);
  };

  const handleResetConfirm = () => {
    setShowConfirm(false);
    onResetAll();
  };

  return (
    <div className="w-[240px] border-r border-[#ede4d8] bg-[#fff8f0] flex flex-col h-screen shrink-0">
      {/* 로고 */}
      <div className="px-4 py-[18px] border-b border-[#ede4d8] flex items-center gap-2">
        <div className="w-7 h-7 rounded-lg bg-[#c4622d] flex items-center justify-center">
          <span className="text-white text-[13px] font-black serif">C</span>
        </div>
        <div>
          <div className="serif text-sm font-bold text-[#2c2416]">ContiCheck</div>
          <div className="text-[9px] text-[#a89880]">이야기 정합성 검사</div>
        </div>
      </div>

      {/* 새 작품 분석하기 */}
      <div className="px-3 py-3">
        <button
          onClick={onNew}
          className="w-full py-2.5 px-3 rounded-[10px] border border-dashed border-[#ede4d8] text-[#c4622d] text-xs font-semibold flex items-center justify-center gap-1.5 transition-colors hover:bg-[#fdeee6] hover:border-[#c4622d]"
        >
          ＋ 새 작품 분석하기
        </button>
      </div>

      {/* 프로젝트 목록 */}
      <div className="flex-1 overflow-auto px-2 py-1">
        <div className="flex items-center justify-between px-2 py-1.5">
          <span className="text-[9px] font-bold text-[#a89880] tracking-[0.06em]">내 작품</span>
          <button
            onClick={() => setShowConfirm(true)}
            title="전체 데이터 초기화"
            className="text-[#c0a898] hover:text-[#b83232] transition-colors text-[11px] leading-none"
          >
            🗑
          </button>
        </div>
        {projects.map(p => {
          const isAct = p.id === activeId;
          const cCnt = p.contradictions?.length || 0;
          const isEditing = editingId === p.id;
          return (
            <div
              key={p.id}
              className={`group relative w-full px-3 py-2.5 rounded-[10px] mb-0.5 transition-all duration-150 cursor-pointer ${
                isAct
                  ? "bg-[#fdeee6] border border-[rgba(196,98,45,0.2)]"
                  : "bg-transparent border border-transparent hover:bg-[#f5efe6]"
              }`}
              onClick={() => !isEditing && onSelect(p.id)}
            >
              {isEditing ? (
                <input
                  ref={inputRef}
                  value={editingName}
                  onChange={e => setEditingName(e.target.value)}
                  onBlur={commitEdit}
                  onKeyDown={e => {
                    if (e.key === 'Enter') commitEdit();
                    if (e.key === 'Escape') setEditingId(null);
                  }}
                  onClick={e => e.stopPropagation()}
                  className="w-full text-xs font-bold text-[#2c2416] bg-white border border-[#c4622d] rounded-md px-1.5 py-0.5 outline-none"
                />
              ) : (
                <div className="flex items-center justify-between gap-1">
                  <div className={`text-xs flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap ${
                    isAct ? "font-bold text-[#c4622d]" : "font-medium text-[#2c2416]"
                  }`}>
                    {p.name}
                  </div>
                  <button
                    onClick={e => startEdit(e, p)}
                    title="이름 변경"
                    className="opacity-0 group-hover:opacity-100 text-[#a89880] hover:text-[#c4622d] transition-all text-[10px] shrink-0"
                  >
                    ✏
                  </button>
                </div>
              )}
              <div className="flex items-center gap-1.5 text-[10px] text-[#a89880] mt-0.5">
                <span>{p.date}</span>
                {cCnt > 0 && <span className="text-[#b83232] font-semibold">⚠ {cCnt}건</span>}
                {cCnt === 0 && p.sources?.length > 0 && (
                  <span className="text-[#2d7a56]">✓ 이상 없음</span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* 초기화 확인 다이얼로그 */}
      {showConfirm && (
        <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center">
          <div className="bg-white rounded-2xl shadow-2xl p-6 mx-4 max-w-[300px] w-full">
            <div className="text-2xl mb-3 text-center">⚠️</div>
            <h3 className="text-sm font-bold text-[#2c2416] mb-2 text-center">전체 데이터 초기화</h3>
            <p className="text-[11px] text-[#6b5c47] text-center leading-relaxed mb-4">
              업로드된 파일, 그래프, AI Search 인덱스가<br />
              <strong>모두 삭제</strong>됩니다. 되돌릴 수 없습니다.
            </p>
            <div className="flex gap-2">
              <button
                onClick={() => setShowConfirm(false)}
                className="flex-1 py-2 rounded-xl border border-[#ede4d8] text-xs font-semibold text-[#6b5c47] hover:bg-[#f5efe6] transition-colors"
              >
                취소
              </button>
              <button
                onClick={handleResetConfirm}
                className="flex-1 py-2 rounded-xl text-xs font-bold text-white transition-colors"
                style={{ background: "#b83232" }}
              >
                삭제
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
