/* Line icons (24 x 24, stroke = currentColor). */
import type { ReactNode } from "react";

const I = ({ children, fill }: { children: ReactNode; fill?: boolean }) => (
  <svg viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
    {children}
  </svg>
);

export const Leaf = () => <I><path d="M5 19c8 0 14-6 14-14-8 0-14 6-14 14z" /><path d="M5 19 13 11" /></I>;
export const Tree = () => <I><circle cx="12" cy="9" r="5.5" /><path d="M12 14.5V21M9 21h6M12 11l-2-2M12 12.5l2.5-2.5" /></I>;
export const Plus = () => <I><path d="M12 5v14M5 12h14" /></I>;
export const Mountain = () => <I><path d="m3 19 6-10 4 6 3-4 5 8z" /><path d="m8 11 1.5 2" /></I>;
export const Rain = () => <I><path d="M7 15a4 4 0 0 1-.6-8A6 6 0 0 1 18 8a3.5 3.5 0 0 1-1 7z" /><path d="m9 18-1 2M13 18l-1 2M17 18l-1 2" /></I>;
export const Battery = () => <I><rect x="3" y="7" width="16" height="10" rx="2.5" /><path d="M21 10.5v3" /><path d="M10 9.5 8 12h4l-2 2.5" /></I>;
export const Wave = () => <I><path d="M3 12h2M7 8v8M11 5v14M15 9v6M19 11v2M21 12h0" /></I>;
export const Thermo = () => <I><path d="M14 14.8V5a2 2 0 0 0-4 0v9.8a4 4 0 1 0 4 0z" /><path d="M12 9v7" /></I>;
export const Gear = () => <I><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></I>;
export const Power = () => <I><path d="M12 3v8" /><path d="M6.4 7.4a8 8 0 1 0 11.2 0" /></I>;
export const Storm = () => <I><path d="M7 14a4 4 0 0 1-.6-8A6 6 0 0 1 18 7a3.5 3.5 0 0 1-1 7" /><path d="m13 11-3 5h4l-3 5" /></I>;
export const Play = () => <I fill><path d="M8 5.5v13l11-6.5z" /></I>;
export const Pause = () => <I fill><rect x="6.5" y="5" width="4" height="14" rx="1" /><rect x="13.5" y="5" width="4" height="14" rx="1" /></I>;
export const Prev = () => <I fill><path d="M18 6v12l-9-6zM6 6h2v12H6z" /></I>;
export const Next = () => <I fill><path d="M6 6v12l9-6zM16 6h2v12h-2z" /></I>;
export const Saw = () => <I><path d="M3 15h13l3-3-3-3H3z" /><path d="M5 15l1 2 1-2 1 2 1-2 1 2 1-2 1 2 1-2" /><path d="M16 9V6h3" /></I>;
export const Shield = () => <I><path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6z" /><path d="m9 12 2 2 4-4" /></I>;
export const Note = () => <I><path d="M9 18V6l10-2v12" /><circle cx="7" cy="18" r="2" /><circle cx="17" cy="16" r="2" /></I>;
export const Check = () => <I><path d="m5 12.5 4.5 4.5L19 7.5" /></I>;
export const Bang = () => <I><path d="M12 6v8M12 18h0" /></I>;
export const Sun = () => <I><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></I>;
export const Moon = () => <I><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z" /></I>;
