'use client';

import { useState, type ReactNode } from 'react';
import { ImageViewer } from '@/components/image-viewer';

export function RefImage({
  paths,
  alt,
  description,
  className = '',
  fallback,
}: {
  paths: string[];
  alt: string;
  description?: string;
  className?: string;
  /** Rendered when no image path resolves. Use this to preserve crop-specific
   *  visual identity (e.g. emoji swatch) instead of the generic "No image". */
  fallback?: ReactNode;
}) {
  const [pathIndex, setPathIndex] = useState(0);
  const [failed, setFailed] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);

  if (failed || paths.length === 0) {
    if (fallback) return <>{fallback}</>;
    return (
      <div
        className={`bg-parchment-100 flex items-center justify-center text-muted-foreground/40 text-xs rounded-lg ${className}`}
      >
        No image
      </div>
    );
  }

  const currentSrc = paths[pathIndex];

  return (
    <>
      <img
        src={currentSrc}
        alt={alt}
        loading="lazy"
        decoding="async"
        className={`object-cover cursor-pointer hover:opacity-90 transition-opacity ${className}`}
        onClick={() => setViewerOpen(true)}
        onError={() => {
          if (pathIndex < paths.length - 1) {
            setPathIndex(pathIndex + 1);
          } else {
            setFailed(true);
          }
        }}
      />
      {viewerOpen && (
        <ImageViewer
          src={currentSrc}
          alt={alt}
          description={description}
          onClose={() => setViewerOpen(false)}
        />
      )}
    </>
  );
}
