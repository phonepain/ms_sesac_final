import { useRef, useState } from 'react';
import { CAT_INFO } from '../../types';

interface CategoryUploadProps {
  categoryKey: 'worldview' | 'settings' | 'scenario';
  files: Array<{id: string, name: string}>;
  pendingFiles: Array<{id: string, name: string, file: File}>;
  onAddFiles: (category: 'worldview' | 'settings' | 'scenario', files: File[]) => void;
  onRemovePending: (category: 'worldview' | 'settings' | 'scenario', id: string) => void;
  onRemoveFile: (category: 'worldview' | 'settings' | 'scenario', id: string) => void;
}

export default function CategoryUpload({ categoryKey, files, pendingFiles, onAddFiles, onRemovePending, onRemoveFile }: CategoryUploadProps) {
  const cat = CAT_INFO[categoryKey];
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOver, setIsOver] = useState(false);

  const isValidFile = (f: File) => /\.(txt|pdf)$/i.test(f.name);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const all = Array.from(e.dataTransfer.files);
      const valid = all.filter(isValidFile);
      if (valid.length < all.length) alert('txt 또는 pdf 파일만 업로드 가능합니다');
      if (valid.length > 0) onAddFiles(categoryKey, valid);
    }
  };

  return (
    <div className="w-full">
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-lg">{cat.i}</span>
        <div>
          <div className="text-xs font-semibold text-[#2c2416]">{cat.l}</div>
        </div>
      </div>

      <div
        className={`dz ${isOver ? 'ov' : ''}`}
        onDragOver={e => { e.preventDefault(); setIsOver(true); }}
        onDragLeave={() => setIsOver(false)}
        onDrop={handleDrop}
        onClick={() => inputRef.current?.click()}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".txt,.pdf"
          className="hidden"
          onChange={e => {
            if (e.target.files) {
              const all = Array.from(e.target.files);
              const valid = all.filter(isValidFile);
              if (valid.length < all.length) alert('txt 또는 pdf 파일만 업로드 가능합니다');
              if (valid.length > 0) onAddFiles(categoryKey, valid);
              e.target.value = '';
            }
          }}
        />
        <div className="text-2xl mb-1">📁</div>
        <p className="text-[#a89880] text-[11px]">클릭하거나 파일을 놓으세요</p>
        <p className="text-[#a89880] text-[9px] mt-0.5">.txt / .pdf</p>
      </div>

      {/* 대기 중 파일 */}
      {pendingFiles.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1">
          {pendingFiles.map(f => (
            <div
              key={f.id}
              className="flex items-center justify-between px-2 py-1.5 rounded-md"
              style={{ background: "rgba(196,124,26,0.08)", borderLeft: "3px solid #c47c1a" }}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-[9px] font-bold text-[#c47c1a] shrink-0">대기</span>
                <span className="text-[11px] text-[#2c2416] truncate">{f.name}</span>
              </div>
              <button
                onClick={e => { e.stopPropagation(); onRemovePending(categoryKey, f.id); }}
                className="text-[#a89880] hover:text-[#b83232] text-xs ml-1 shrink-0"
              >✕</button>
            </div>
          ))}
        </div>
      )}

      {/* 업로드 완료 파일 */}
      {files.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1">
          {files.map(f => (
            <div
              key={f.id}
              className="flex items-center justify-between px-2 py-1.5 rounded-md"
              style={{ background: "rgba(45,122,86,0.08)", borderLeft: "3px solid #2d7a56" }}
            >
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-[9px] font-bold text-[#2d7a56] shrink-0">완료</span>
                <span className="text-[11px] text-[#2c2416] truncate">{f.name}</span>
              </div>
              <button
                onClick={e => { e.stopPropagation(); onRemoveFile(categoryKey, f.id); }}
                className="text-[#a89880] hover:text-[#b83232] text-xs ml-1 shrink-0"
              >✕</button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
