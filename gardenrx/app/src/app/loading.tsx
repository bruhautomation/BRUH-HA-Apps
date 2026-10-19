// Route-level loading UI. Next wraps each page in a Suspense boundary using
// this as the fallback, so navigations paint an instant skeleton instead of
// blocking on the page's server data (every page here is force-dynamic).
export default function Loading() {
  return (
    <div className="page" role="status" aria-label="Loading">
      <span className="sr-only">Loading…</span>
      <div className="section-title" style={{ marginBottom: 16 }}>
        <div className="skeleton" style={{ height: 26, width: 180 }} />
      </div>

      <div className="skeleton" style={{ height: 158, borderRadius: 'var(--r-xl)' }} />

      <div className="detail-grid" style={{ marginTop: 'var(--gap)' }}>
        <div className="flex flex-col gap-[var(--gap)]">
          <div className="skeleton" style={{ height: 124, borderRadius: 'var(--r-lg)' }} />
          <div className="skeleton" style={{ height: 96, borderRadius: 'var(--r-lg)' }} />
        </div>
        <div className="flex flex-col gap-[var(--gap)]">
          <div className="skeleton" style={{ height: 210, borderRadius: 'var(--r-lg)' }} />
          <div className="skeleton" style={{ height: 96, borderRadius: 'var(--r-lg)' }} />
        </div>
      </div>
    </div>
  );
}
