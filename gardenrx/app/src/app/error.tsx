'use client'; // Error boundaries must be Client Components

import { useEffect } from 'react';
import Link from 'next/link';
import { RotateCw, House, TriangleAlert } from 'lucide-react';

// Catches runtime errors in any route segment and renders inside the app shell
// (sidebar + topbar stay interactive). `unstable_retry` re-fetches and
// re-renders the segment (Next 16.2+); `reset` is the older fallback.
export default function Error({
  error,
  unstable_retry,
  reset,
}: {
  error: Error & { digest?: string };
  unstable_retry?: () => void;
  reset?: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  const retry = unstable_retry ?? reset ?? (() => window.location.reload());

  return (
    <div className="page">
      <div
        className="card panel"
        style={{ maxWidth: 460, margin: '48px auto', textAlign: 'center' }}
      >
        <div
          className="mx-auto grid size-12 place-items-center rounded-full"
          style={{ background: 'var(--danger-bg)', color: 'var(--danger)' }}
        >
          <TriangleAlert className="size-6" />
        </div>
        <h2 className="font-display" style={{ fontSize: 20, marginTop: 14 }}>
          Something went wrong
        </h2>
        <p className="text-ink-2" style={{ fontSize: 14, marginTop: 8, lineHeight: 1.55 }}>
          This page hit an error while loading. Your data is safe — try again.
        </p>
        <div className="flex items-center justify-center gap-2" style={{ marginTop: 18 }}>
          <button type="button" onClick={() => retry()} className="btn btn-primary">
            <RotateCw className="size-4" /> Try again
          </button>
          <Link href="/" className="btn">
            <House className="size-4" /> Today
          </Link>
        </div>
      </div>
    </div>
  );
}
