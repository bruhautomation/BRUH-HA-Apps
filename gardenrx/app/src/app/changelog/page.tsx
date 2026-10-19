import { promises as fs } from 'node:fs';
import path from 'node:path';
import Link from 'next/link';
import { ChevronLeft } from 'lucide-react';
import { renderChangelog } from '@/lib/render-changelog';
import { APP_VERSION } from '@/lib/version';

// Matches the rest of the app — every page is dynamic so the layout's
// SearchWrapper (which queries the database) doesn't get pulled into a static
// prerender pass without env vars.
export const dynamic = 'force-dynamic';

async function loadChangelog(): Promise<string> {
  const file = process.env.GARDENRX_CHANGELOG || path.join(process.cwd(), 'CHANGELOG.md');
  try {
    return await fs.readFile(/*turbopackIgnore: true*/ file, 'utf8');
  } catch {
    return '# Changelog\n\nNo changelog file found.';
  }
}

export const metadata = {
  title: 'Changelog · GardenRX',
};

export default async function ChangelogPage() {
  const md = await loadChangelog();

  return (
    <div className="page">
      <Link href="/" className="btn btn-ghost mb-3.5">
        <ChevronLeft className="size-4" /> Today
      </Link>

      <div className="section-title">
        <h2>Changelog</h2>
        <span className="meta">Release notes · v{APP_VERSION}</span>
      </div>

      <article className="mx-auto max-w-3xl">{renderChangelog(md)}</article>

      <footer className="mx-auto mt-10 max-w-3xl border-t border-border/40 pt-6 text-center">
        <p className="text-[11px] text-muted-foreground/60">
          Format follows{' '}
          <a
            href="https://keepachangelog.com/en/1.1.0/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-700/80 hover:text-emerald-700 underline underline-offset-2"
          >
            Keep a Changelog
          </a>
          {' · '}versioning per{' '}
          <a
            href="https://semver.org/"
            target="_blank"
            rel="noopener noreferrer"
            className="text-emerald-700/80 hover:text-emerald-700 underline underline-offset-2"
          >
            SemVer
          </a>
        </p>
      </footer>
    </div>
  );
}
