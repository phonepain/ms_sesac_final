import { useState, useRef, useEffect } from 'react';
import { aiApi } from '../../api/endpoints';

interface Message {
  r: 'user' | 'system' | 'ai';
  t: string;
}

export default function AiChatPanel() {
  const [messages, setMessages] = useState<Message[]>([
    { r: 'system', t: '안녕하세요! 작품의 인물, 설정, 사건에 대해 무엇이든 물어보세요 😊' }
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
      const res = await aiApi.query(query);
      const answerText = res.sources?.length
        ? `${res.answer}\n\n📌 출처: ${res.sources.join(', ')}`
        : res.answer;
      setMessages(prev => [...prev, { r: 'ai', t: answerText }]);
    } catch (e: any) {
      const detail = e?.message || '오류가 발생했습니다.';
      setMessages(prev => [...prev, { r: 'system', t: `⚠️ ${detail}` }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="bg-white border border-[#ede4d8] rounded-2xl flex flex-col h-full"
      style={{ minHeight: '360px', boxShadow: '0 2px 8px rgba(44,36,22,0.06)' }}
    >
      {/* 헤더 — 상단 고정 */}
      <div className="flex-shrink-0 px-4 py-3 border-b border-[#ede4d8] flex items-center gap-2 bg-[#fff8f0] rounded-t-2xl">
        <div className="w-7 h-7 rounded-full bg-[#c4622d] flex items-center justify-center text-base">🤖</div>
        <div>
          <div className="text-xs font-bold text-[#2c2416]">AI에게 질문하기</div>
          <div className="text-[9px] text-[#a89880]">작품 지식 그래프 기반</div>
        </div>
      </div>

      {/* 메시지 — 남은 공간 채우며 스크롤 */}
      <div className="flex-1 overflow-y-auto p-3 flex flex-col gap-2">
        {messages.map((m, i) => (
          <div
            key={i}
            className={`max-w-[88%] rounded-xl px-3 py-2 border ${
              m.r === 'user'
                ? 'self-end bg-[#fdeee6] border-[rgba(196,98,45,0.15)]'
                : m.r === 'system'
                  ? 'self-start bg-[#f5efe6] border-[#ede4d8]'
                  : 'self-start bg-[#e8f4ee] border-[rgba(45,122,86,0.15)]'
            }`}
          >
            <p className="text-[11px] text-[#2c2416] leading-relaxed whitespace-pre-wrap">{m.t}</p>
          </div>
        ))}
        {loading && (
          <div className="self-start text-[#a89880] text-[11px] italic">생각하는 중...</div>
        )}
        <div ref={endRef} />
      </div>

      {/* 입력창 — 하단 고정 */}
      <div className="flex-shrink-0 p-2.5 border-t border-[#ede4d8] flex gap-2">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') handleSend(); }}
          placeholder="예: A와 B의 관계가 어떻게 되나요?"
          className="flex-1 bg-[#fff8f0] border border-[#ede4d8] rounded-lg px-3 py-2 text-[11px] text-[#2c2416] outline-none focus:border-[#c4622d] transition-colors"
        />
        <button
          onClick={handleSend}
          disabled={!input.trim() || loading}
          className={`px-3.5 py-2 rounded-lg text-[12px] font-bold transition-colors ${
            input.trim() && !loading
              ? 'bg-[#c4622d] text-white hover:bg-[#a8511f]'
              : 'bg-[#f5efe6] text-[#a89880]'
          }`}
        >
          전송
        </button>
      </div>
    </div>
  );
}
