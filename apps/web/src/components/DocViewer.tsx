"use client";
import { useEffect, useRef, useState } from "react";

export interface Box { id: string; box: number[]; label: string }
interface Props { docId: number; page?: number; boxes: Box[]; active: string | null; onActive: (id: string | null) => void; alt: string }

/** The page as a picture with a box over each extracted value. Boxes are fractions of the page, so they stay put at any width. */
export function DocViewer({ docId, page = 1, boxes, active, onActive, alt }: Props) {
  const wrap = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const el = wrap.current?.querySelector<HTMLElement>(`[data-box="${active}"]`);
    const c = wrap.current;
    if (!el || !c) return;
    const r = el.getBoundingClientRect(), cr = c.getBoundingClientRect();
    if (r.top < cr.top || r.bottom > cr.bottom) c.scrollTo({ top: el.offsetTop - c.clientHeight / 3, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  }, [active]);
  if (failed) return <div className="ll-viewer" role="note"><p style={{ margin: 13 }}>The page could not be drawn. The fields on the right are still there.</p></div>;
  return (
    <div className="ll-viewer" ref={wrap} tabIndex={0} aria-label="Document page. The same information is in the field list.">
      <div className="ll-viewer__page">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`/api/documents/${docId}/page/${page}.png`} alt={alt} className="ll-viewer__img" draggable={false} onError={() => setFailed(true)} />
        {boxes.map((b) => (
          <button key={b.id} type="button" tabIndex={-1} aria-hidden="true" data-box={b.id} className={`ll-box ${active === b.id ? "ll-box--on" : ""}`} title={b.label}
            style={{ left: `${(b.box[0] ?? 0) * 100}%`, top: `${(b.box[1] ?? 0) * 100}%`, width: `${((b.box[2] ?? 0) - (b.box[0] ?? 0)) * 100}%`, height: `${((b.box[3] ?? 0) - (b.box[1] ?? 0)) * 100}%` }}
            onPointerEnter={() => onActive(b.id)} onPointerLeave={() => onActive(null)} onClick={() => onActive(b.id)} />
        ))}
      </div>
    </div>
  );
}
