'use client';

import { useState, useEffect } from 'react';
import { FileText } from 'lucide-react';
import Link from 'next/link';
import { withBase } from '@/lib/base-path';

export function LabelViewer({ productId }: { productId: number }) {
  const [hasLabel, setHasLabel] = useState(false);

  useEffect(() => {
    let cancelled = false;
    // HEAD request to the text label — only show the link if the file actually exists.
    fetch(withBase(`/data/labels/${productId}.txt`), { method: 'HEAD' })
      .then((r) => {
        if (!cancelled) setHasLabel(r.ok);
      })
      .catch(() => {
        if (!cancelled) setHasLabel(false);
      });
    return () => {
      cancelled = true;
    };
  }, [productId]);

  if (!hasLabel) return null;

  return (
    <Link
      href={`/products/${productId}/label`}
      className="rounded-xl ring-1 ring-black/[0.04] bg-card shadow-sm overflow-hidden w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-muted/30 transition-colors"
    >
      <FileText className="w-4 h-4 text-emerald-600 shrink-0" />
      <span className="text-sm font-medium flex-1">View Label</span>
    </Link>
  );
}
