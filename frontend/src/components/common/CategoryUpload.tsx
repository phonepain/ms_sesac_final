import { useRef, useState } from 'react';
import { CAT_INFO } from '../../types';

interface CategoryUploadProps {
  categoryKey: 'worldview' | 'settings' | 'scenario';
  files: Array<{id: string, name: string}>;
  onAddFiles: (category: 'worldview' | 'settings' | 'scenario', files: File[]) => void;
  onRemoveFile: (category: 'worldview' | 'settings' | 'scenario', id: string) => void;
}

export default function CategoryUpload({ categoryKey, files, onAddFiles, onRemoveFile }: CategoryUploadProps) {
  const cat = CAT_INFO[categoryKey];
  const inputRef = useRef<HTMLInputElement>(null);
  const [isOver, setIsOver] = useState(false);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsOver(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files).filter(f => f.name.match(/\.(txt|pdf)$/i));
      if (droppedFiles.length > 0) onAddFiles(categoryKey, droppedFiles);
    }
  };

  return (
    <div>
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
              onAddFiles(categoryKey, Array.from(e.target.files));
              e.target.value = '';
            }
          }}
        />
        <div className="text-2xl mb-1">📁</div>
        <p className="text-[#a89880] text-[11px]">클릭하거나 파일을 놓으세요</p>
        <p className="text-[#a89880] text-[9px] mt-0.5">.txt / .pdf</p>
      </div>

      {files.length > 0 && (
        <div className="mt-1.5 flex flex-col gap-1">
          {files.map(f => (
            <div
              key={f.id}
              className="flex items-center justify-between px-2 py-1.5 bg-[#f5efe6] rounded-md"
              style={{ borderLeft: `3px solid ${cat.c}` }}
            >
              <span className="text-[11px] text-[#2c2416] truncate">{f.name}</span>
              <button
                onClick={e => { e.stopPropagation(); onRemoveFile(categoryKey, f.id); }}
                className="text-[#a89880] hover:text-[#b83232] text-xs ml-1"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
