import { useRef, useState } from 'react';
import { Up, Tr } from './Icons';
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
      if (droppedFiles.length > 0) {
        onAddFiles(categoryKey, droppedFiles);
      }
    }
  };

  return (
    <div>
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-sm">{cat.i}</span>
        <span className="text-[11px] font-semibold" style={{ color: cat.c }}>{cat.l}</span>
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
              e.target.value = ''; // reset
            }
          }}
        />
        <div className="flex justify-center text-[#71717a] mb-1"><Up /></div>
        <p className="text-[#71717a] text-[9px] mt-0.5">TXT / PDF</p>
      </div>

      {files.length > 0 && (
        <div className="mt-1 flex flex-col gap-0.5">
          {files.map(f => (
            <div 
              key={f.id} 
              className="flex items-center justify-between px-1.5 py-[3px] bg-[rgba(39,39,42,0.15)] rounded-sm border-l-2"
              style={{ borderLeftColor: cat.c }}
            >
              <span className="text-[10px] text-[#d4d4d8] truncate">{f.name}</span>
              <button 
                onClick={(e) => { e.stopPropagation(); onRemoveFile(categoryKey, f.id); }} 
                className="text-[#52525b] hover:text-[#f87171] p-0.5"
              >
                <Tr />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
