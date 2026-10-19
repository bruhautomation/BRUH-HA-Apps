'use client'; // Error boundaries must be Client Components

// Replaces the root layout when an error escapes it, so it must ship its own
// <html>/<body> and self-contained styles (globals.css is not guaranteed here).
export default function GlobalError({
  unstable_retry,
  reset,
}: {
  error: Error & { digest?: string };
  unstable_retry?: () => void;
  reset?: () => void;
}) {
  const retry = unstable_retry ?? reset ?? (() => window.location.reload());

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'grid',
          placeItems: 'center',
          background: '#0f1714',
          color: '#e7efe9',
          fontFamily: 'system-ui, -apple-system, sans-serif',
          padding: 24,
        }}
      >
        <title>Something went wrong — GardenRX</title>
        <div style={{ maxWidth: 420, textAlign: 'center' }}>
          <h1 style={{ fontSize: 22, margin: '0 0 10px', fontWeight: 600 }}>
            Something went wrong
          </h1>
          <p style={{ fontSize: 15, lineHeight: 1.55, color: '#a9bdb2', margin: '0 0 22px' }}>
            GardenRX hit an unexpected error. Reloading usually clears it.
          </p>
          <button
            type="button"
            onClick={() => retry()}
            style={{
              background: '#3fae7a',
              color: '#06120c',
              border: 'none',
              borderRadius: 10,
              padding: '11px 20px',
              fontSize: 14,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
