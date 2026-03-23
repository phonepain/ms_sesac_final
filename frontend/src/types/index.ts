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
    n: string;
    cat: 'worldview' | 'settings' | 'scenario';
    ent: number;
    fct: number;
  }>;
  graphBuilt: {
    ws: boolean;
    sc: boolean;
  };
  contradictions: Contradiction[];
  versions: Version[];
}

export type SeverityType = 'critical' | 'warning' | 'info';

export const SV_COLORS = {
  critical: { bg: "rgba(127,29,29,.4)", bd: "rgba(239,68,68,.4)", bg2: "#ef4444", tx: "#f87171", l: "심각" },
  warning:  { bg: "rgba(120,53,15,.3)",  bd: "rgba(245,158,11,.35)", bg2: "#f59e0b", tx: "#fbbf24", l: "주의" },
  info:     { bg: "rgba(12,74,110,.3)",  bd: "rgba(14,165,233,.25)", bg2: "#0ea5e9", tx: "#38bdf8", l: "참고" }
};

export const CAT_INFO = {
  worldview: { l: "세계관",  c: "#a78bfa", i: "🌍" },
  settings:  { l: "설정집",  c: "#f472b6", i: "📋" },
  scenario:  { l: "시나리오", c: "#34d399", i: "🎬" }
};

export type DecisionType = 'intentional' | 'fix' | 'deferred';

export interface Contradiction {
  id: string;
  sv: SeverityType;
  tp: string;
  ch: string;
  ft: string;
  dl: string;
  ds: string;
  ev: Array<{ sr: string; lc: string; tx: string }>;
  cf: number;
  sg: string;
  al: string | null;
  ot?: string;
}

export interface StagedFix {
  id: string;
  ch?: string;
  tp?: string;
  ot?: string;
  fixedText?: string;
  isIntentional?: boolean;
  intentNote?: string;
}

export interface Version {
  id: string;
  vr: string;
  dt: string;
  fx: number;
  ds: string;
  src?: string;
  content?: string;
}
