'use client';

import { useEffect, useRef } from 'react';
import type { StageInfo } from '@/lib/growth-stages';
import { stageVarColor } from '@/lib/stage-color';

/** Horizontal phenology track with a "Now" pill + ringed dot on the active stage. */
export function StageTimeline({
  stages,
  currentIndex,
}: {
  stages: StageInfo[];
  currentIndex: number;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const currentRef = useRef<HTMLDivElement>(null);

  // On phones the track scrolls horizontally — start it centered on "Now".
  // Observed rather than run once: the track only becomes scrollable after
  // layout/styles settle, which can happen after mount.
  useEffect(() => {
    const track = trackRef.current;
    const node = currentRef.current;
    if (!track || !node) return;
    let centered = false;
    const center = () => {
      if (centered || track.scrollWidth <= track.clientWidth) return;
      const trackRect = track.getBoundingClientRect();
      const nodeRect = node.getBoundingClientRect();
      track.scrollLeft += nodeRect.left - trackRect.left - trackRect.width / 2 + nodeRect.width / 2;
      centered = true;
    };
    center();
    const observer = new ResizeObserver(center);
    observer.observe(track);
    return () => observer.disconnect();
  }, [currentIndex]);

  return (
    <div className="stage-track" ref={trackRef}>
      {stages.map((info, i) => {
        const state = i < currentIndex ? 'done' : i === currentIndex ? 'current' : '';
        return (
          <div
            className={`stage-node${state ? ` ${state}` : ''}`}
            key={info.stage}
            ref={state === 'current' ? currentRef : undefined}
            style={{ ['--stg' as string]: stageVarColor(info.stage) }}
          >
            <div className="sn-line" />
            {state === 'current' && <div className="sn-now">Now</div>}
            <div className="sn-dot">{state === 'current' && <span className="sn-pin" />}</div>
            <div className="sn-lbl">{info.label}</div>
          </div>
        );
      })}
    </div>
  );
}
