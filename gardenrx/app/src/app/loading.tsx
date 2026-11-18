import { PageShell } from '@/components/ui/page-shell';

// Route-level loading UI. Next wraps each page in a Suspense boundary using
// this as the fallback, so navigations paint an instant skeleton instead of
// blocking on the page's server data (every page here is force-dynamic).
export default function Loading() {
  return (
    <PageShell
      role="status"
      aria-label="Loading"
      header={<div className="skeleton" style={{ height: 28, width: 180 }} />}
    >
      <span className="sr-only">Loading…</span>

      <div className="skeleton" style={{ height: 160 }} />

      <div className="detail-grid">
        <div className="stack">
          <div className="skeleton" style={{ height: 124 }} />
          <div className="skeleton" style={{ height: 96 }} />
        </div>
        <div className="stack">
          <div className="skeleton" style={{ height: 212 }} />
          <div className="skeleton" style={{ height: 96 }} />
        </div>
      </div>
    </PageShell>
  );
}
