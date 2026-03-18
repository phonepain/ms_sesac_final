import { useState, useRef, useEffect } from 'react';
import { AI, Ld, Sn } from '../common/Icons';
import { aiApi } from '../../api/endpoints';

interface AiChatPanelProps {
  floating?: boolean;
}

interface Message {
  r: 'user' | 'system' | 'ai';
  t: string;
}

export default function AiChatPanel({ floating = false }: AiChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([
    { r: 'system', t: '구축된 지식 그래프를 기반으로 질문할 수 있습니다. 캐릭터, 설정, 모순에 대해 자유롭게 물어보세요.' }
  ]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    
    const query = input.trim();
    setInput('');
    setLoading(true);
    setMessages(prev => [...prev, { r: 'user', t: query }]);

    try {
      // API call to the backend
      const res = await aiApi.query(query);
      
      const answerText = `${res.answer}\n\n[출처: ${(res.sources || []).join(', ')}]`;
      setMessages(prev => [...prev, { r: 'ai', t: answerText }]);
    } catch (error) {
      setMessages(prev => [...prev, { r: 'system', t: 'API 통신 중 오류가 발생했습니다. 나중에 다시 시도해주세요.' }]);
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  const floatingStyles = floating 
    ? "fixed bottom-5 right-5 w-[380px] h-[440px] z-45 shadow-[0_16px_48px_rgba(0,0,0,0.5)]" 
    : "h-[320px] lg:h-[440px]"; // Base responsive height if not floating

  return (
    <div className={`bg-[rgba(12,12,18,0.95)] border border-[rgba(63,63,70,0.2)] rounded-[14px] flex flex-col ${floatingStyles}`}>
      
      <div className="px-3.5 py-2.5 border-b border-[rgba(63,63,70,0.12)] flex items-center gap-1.5 bg-[rgba(16,185,129,0.03)] rounded-t-[14px]">
        <div className="w-[22px] h-[22px] rounded-md bg-gradient-to-br from-[#10b981] to-[#0d9488] flex items-center justify-center text-white">
          <AI />
        </div>
        <span className="text-xs font-bold text-white">AI 질의</span>
        <span className="text-[9px] text-[#52525b]">GraphRAG 기반</span>
      </div>
      
      <div className="flex-1 overflow-auto p-2.5 flex flex-col gap-1.5 scrollbar-thin">
        {messages.map((m, i) => (
          <div 
            key={i} 
            className={`max-w-[85%] rounded-[10px] px-3 py-2 border ${
              m.r === 'user' 
                ? 'self-end bg-[rgba(16,185,129,0.1)] border-[rgba(16,185,129,0.15)]' 
                : m.r === 'system' 
                  ? 'self-start bg-[rgba(139,92,246,0.06)] border-[rgba(63,63,70,0.08)]' 
                  : 'self-start bg-[rgba(39,39,42,0.25)] border-[rgba(63,63,70,0.08)]'
            }`}
          >
            <p className={`text-[11px] leading-relaxed whitespace-pre-wrap ${
              m.r === 'system' ? 'text-[#a78bfa]' : 'text-[#e4e4e7]'
            }`}>
              {m.t}
            </p>
          </div>
        ))}
        {loading && (
          <div className="self-start text-[#52525b] text-[10px] flex items-center gap-1 mt-1">
            <Ld /> 생각 중...
          </div>
        )}
        <div ref={endRef} />
      </div>
      
      <div className="p-2 border-t border-[rgba(63,63,70,0.1)] flex gap-1.5">
        <input 
          value={input} 
          onChange={e => setInput(e.target.value)} 
          onKeyDown={e => { if (e.key === 'Enter') handleSend(); }} 
          placeholder="질문을 입력하세요..." 
          className="flex-1 bg-[rgba(39,39,42,0.35)] border border-[rgba(63,63,70,0.2)] rounded-lg px-3 py-1.5 text-[11px] text-[#e4e4e7] outline-none focus:border-[#10b981]/50 transition-colors"
        />
        <button 
          onClick={handleSend} 
          disabled={!input.trim() || loading} 
          className={`px-3.5 py-1.5 rounded-lg text-[11px] font-semibold flex items-center justify-center ${
            input.trim() && !loading 
              ? 'bg-gradient-to-br from-[#059669] to-[#0d9488] text-white hover:opacity-90' 
              : 'bg-[#27272a] text-[#52525b]'
          } transition-all`}
        >
          <Sn />
        </button>
      </div>
    </div>
  );
}
