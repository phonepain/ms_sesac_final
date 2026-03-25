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

// Warm, author-friendly color palette (writer.html style)
export const SV_COLORS = {
  critical: {
    bg: "#fdeaea",
    bd: "rgba(184,50,50,0.2)",
    bg2: "#c0392b",
    tx: "#b83232",
    l: "심각한 모순",
    emoji: "🔴"
  },
  warning: {
    bg: "#fef3db",
    bd: "rgba(196,124,26,0.2)",
    bg2: "#e67e22",
    tx: "#c47c1a",
    l: "확인 필요",
    emoji: "🟡"
  },
  info: {
    bg: "#e8f4ee",
    bd: "rgba(45,122,86,0.2)",
    bg2: "#27ae60",
    tx: "#2d7a56",
    l: "참고",
    emoji: "🟢"
  }
};

export const CAT_INFO = {
  worldview: { l: "세계관",  c: "#7c5cbf", i: "🌍" },
  settings:  { l: "설정집",  c: "#c4622d", i: "📋" },
  scenario:  { l: "시나리오", c: "#2d7a56", i: "🎬" }
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
  chunkId?: string;
  chunkContent?: string;
}

export interface StagedFix {
  id: string;
  ch?: string;
  tp?: string;
  ot?: string;
  fixedText?: string;
  isIntentional?: boolean;
  intentNote?: string;
  chunkId?: string;
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
