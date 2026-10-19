'use client';

import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { X, ZoomIn, ZoomOut } from 'lucide-react';

interface Props {
  src: string;
  alt: string;
  description?: string;
  onClose: () => void;
}

export function ImageViewer({ src, alt, description, onClose }: Props) {
  const [scale, setScale] = useState(1);
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const posStart = useRef({ x: 0, y: 0 });

  // Lock body scroll while open
  useEffect(() => {
    document.body.style.overflow = 'hidden';
    return () => {
      document.body.style.overflow = '';
    };
  }, []);

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, [onClose]);

  function zoomIn() {
    setScale((s) => Math.min(s * 1.5, 8));
  }

  function zoomOut() {
    setScale((s) => Math.max(s / 1.5, 0.5));
  }

  function handlePointerDown(e: React.PointerEvent) {
    if (scale <= 1) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY };
    posStart.current = { ...position };
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e: React.PointerEvent) {
    if (!dragging) return;
    setPosition({
      x: posStart.current.x + (e.clientX - dragStart.current.x),
      y: posStart.current.y + (e.clientY - dragStart.current.y),
    });
  }

  function handlePointerUp() {
    setDragging(false);
  }

  function handleDoubleClick() {
    if (scale > 1) {
      setScale(1);
      setPosition({ x: 0, y: 0 });
    } else {
      setScale(3);
    }
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-parchment-200/70 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      {/* Popup card — matches app width */}
      <div className="w-full max-w-lg mx-4 max-h-[85vh] flex flex-col rounded-2xl overflow-hidden bg-card shadow-2xl ring-1 ring-black/[0.08]">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/40 shrink-0">
          <div className="flex items-center gap-1.5">
            <button
              onClick={zoomOut}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              <ZoomOut className="w-4 h-4" />
            </button>
            <span className="text-muted-foreground/50 text-[11px] font-mono tabular-nums min-w-[2.5rem] text-center">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={zoomIn}
              className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
            >
              <ZoomIn className="w-4 h-4" />
            </button>
          </div>
          <p className="text-sm font-heading font-semibold truncate mx-3 flex-1 text-center text-foreground">
            {alt}
          </p>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto min-h-0">
          {/* Image */}
          <div
            className="flex items-center justify-center bg-parchment-50 overflow-hidden cursor-grab active:cursor-grabbing"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onDoubleClick={handleDoubleClick}
            style={{ minHeight: '220px' }}
          >
            <img
              src={src}
              alt={alt}
              className="max-w-full object-contain select-none transition-transform duration-150"
              style={{
                transform: `translate(${position.x}px, ${position.y}px) scale(${scale})`,
              }}
              draggable={false}
            />
          </div>

          {/* Description */}
          {description && (
            <div className="px-4 py-4 border-t border-border/40">
              <p className="text-sm text-foreground/80 leading-relaxed whitespace-pre-line">
                {description}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
