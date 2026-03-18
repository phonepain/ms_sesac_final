export interface Project {
  id: string;
  name: string;
  date: string;
  kb: {
    characters: number;
    facts: number;
    relationships: number;
    events: number;
    traits: number;
  };
  sources: Array<{
    id: string;
    n: string; // name
    cat: 'worldview' | 'settings' | 'scenario';
    ent: number;
    fct: number;
  }>;
  graphBuilt: {
    ws: boolean;
    sc: boolean;
  };
  contradictions: Array<any>;
  versions: Array<any>;
}

export type SeverityType = 'critical' | 'warning' | 'info';

export const SV_COLORS = {
  critical: { bg: "rgba(127,29,29,.4)", bd: "rgba(239,68,68,.4)", bg2: "#ef4444", tx: "#f87171" },
  warning: { bg: "rgba(120,53,15,.3)", bd: "rgba(245,158,11,.35)", bg2: "#f59e0b", tx: "#fbbf24" },
  info: { bg: "rgba(12,74,110,.3)", bd: "rgba(14,165,233,.25)", bg2: "#0ea5e9", tx: "#38bdf8" }
};

export const CAT_INFO = {
  worldview: { l: "세계관", c: "#a78bfa", i: "🌍" },
  settings: { l: "설정집", c: "#f472b6", i: "📋" },
  scenario: { l: "시나리오", c: "#34d399", i: "🎬" }
};
