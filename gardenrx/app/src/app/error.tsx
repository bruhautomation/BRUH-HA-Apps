'use client'; // Error boundaries must be Client Components

import { useEffect } from 'react';
import Link from 'next/link';
import { RotateCw, House, TriangleAlert } from 'lucide-react';
import { PageShell } from '@/components/ui/page-shell';

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
    <PageShell width="narrow">
      <div className="card panel mx-auto w-full max-w-md text-center">
        <div
          className="mx-auto grid size-12 place-items-center rounded-full"
          style={{ background: 'var(--danger-bg)', color: 'var(--danger)' }}
        >
          <TriangleAlert className="size-6" />
        </div>
        <h2 className="font-display mt-3 text-xl">Something went wrong</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-2">
          This page hit an error while loading. Your data is safe — try again.
        </p>
        <div className="mt-4 flex items-center justify-center gap-2">
          <button type="button" onClick={() => retry()} className="btn btn-primary">
            <RotateCw className="size-4" /> Try again
          </button>
          <Link href="/" className="btn">
            <House className="size-4" /> Today
          </Link>
        </div>
      </div>
    </PageShell>
  );
}
