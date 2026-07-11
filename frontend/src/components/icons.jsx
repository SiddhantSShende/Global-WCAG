// Inline SVG icons (no external icon font — self-contained, offline-friendly).
const S = { fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round" };

export const Logo = (p) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" {...p}>
    <circle cx="12" cy="12" r="9" /><ellipse cx="12" cy="12" rx="4" ry="9" />
    <path d="M3 12h18M4.6 7h14.8M4.6 17h14.8" />
  </svg>
);
export const Sun = (p) => (
  <svg viewBox="0 0 24 24" {...S} {...p}><circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></svg>
);
export const Moon = (p) => (
  <svg viewBox="0 0 24 24" {...S} {...p}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>
);
export const Key = (p) => (
  <svg viewBox="0 0 24 24" {...S} {...p}><path d="M21 2l-2 2m-7.6 7.6a5 5 0 1 0-1 1L15 15l2 2 2-2-2-2 3-3-2-2" /></svg>
);
export const Play = (p) => (<svg viewBox="0 0 24 24" {...S} {...p}><path d="M5 3l14 9-14 9V3z" /></svg>);
export const Check = (p) => (<svg viewBox="0 0 24 24" {...S} {...p}><path d="M20 6L9 17l-5-5" /></svg>);
export const ArrowRight = (p) => (<svg viewBox="0 0 24 24" {...S} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);
export const Website = (p) => (
  <svg viewBox="0 0 24 24" {...S} {...p}><rect x="3" y="4" width="18" height="14" rx="2" />
    <path d="M3 9h18M8 18v3M16 18v3M6 21h12" /></svg>
);
export const Android = (p) => (
  <svg viewBox="0 0 24 24" {...S} {...p}><rect x="6" y="2" width="12" height="20" rx="2" /><path d="M11 18h2" /></svg>
);
export const Apple = (p) => (
  <svg viewBox="0 0 24 24" {...S} {...p}><rect x="6" y="2" width="12" height="20" rx="3" /><path d="M10 5h4" /></svg>
);
