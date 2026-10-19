import React from 'react';
import { Sparkles, Wrench, RefreshCw, Trash2, AlertTriangle, ShieldAlert, Tag } from 'lucide-react';

/**
 * Structured renderer for our CHANGELOG.md.
 *
 * Parses the Keep-a-Changelog dialect we actually use (`## [version] - date`,
 * `### Added/Changed/Fixed/...`, `- ` bullets, inline `**bold**`, `` `code` ``,
 * and `[text](url)`) into release cards with color-coded sections.
 *
 * Anything that doesn't match the structure falls back to a paragraph above
 * the first release.
 */

// ── Section taxonomy ─────────────────────────────────────────────────

type SectionKind = 'Added' | 'Changed' | 'Deprecated' | 'Removed' | 'Fixed' | 'Security' | 'Other';

interface SectionStyle {
  badge: string; // pill background + text classes
  ring: string; // pill ring
  icon: React.ComponentType<{ className?: string }>;
  accent: string; // bullet marker color
}

const SECTION_STYLES: Record<SectionKind, SectionStyle> = {
  Added: {
    badge: 'bg-emerald-100 text-emerald-800',
    ring: 'ring-emerald-200/60',
    icon: Sparkles,
    accent: 'marker:text-emerald-500/70',
  },
  Fixed: {
    badge: 'bg-terra-100 text-terra-800',
    ring: 'ring-terra-200/60',
    icon: Wrench,
    accent: 'marker:text-terra-500/70',
  },
  Changed: {
    badge: 'bg-amber-100 text-amber-800',
    ring: 'ring-amber-200/60',
    icon: RefreshCw,
    accent: 'marker:text-amber-500/70',
  },
  Removed: {
    badge: 'bg-stone-200 text-stone-700',
    ring: 'ring-stone-300/60',
    icon: Trash2,
    accent: 'marker:text-stone-500/70',
  },
  Deprecated: {
    badge: 'bg-amber-100 text-amber-800',
    ring: 'ring-amber-200/60',
    icon: AlertTriangle,
    accent: 'marker:text-amber-500/70',
  },
  Security: {
    badge: 'bg-red-100 text-red-800',
    ring: 'ring-red-200/60',
    icon: ShieldAlert,
    accent: 'marker:text-red-500/70',
  },
  Other: {
    badge: 'bg-muted text-foreground/70',
    ring: 'ring-border/60',
    icon: Tag,
    accent: 'marker:text-muted-foreground/70',
  },
};

function classifySection(label: string): SectionKind {
  const l = label.trim().toLowerCase();
  if (l.startsWith('add')) return 'Added';
  if (l.startsWith('fix')) return 'Fixed';
  if (l.startsWith('chang') || l.startsWith('update')) return 'Changed';
  if (l.startsWith('remov') || l.startsWith('delete')) return 'Removed';
  if (l.startsWith('deprec')) return 'Deprecated';
  if (l.startsWith('secur')) return 'Security';
  return 'Other';
}

// ── Parsing ──────────────────────────────────────────────────────────

interface Section {
  kind: SectionKind;
  rawLabel: string;
  items: string[];
}

interface Release {
  /** The text inside `## [...]` — e.g. "0.2.0" or "Unreleased". */
  version: string;
  /** Optional date string parsed after the version (e.g. "2026-05-18"). */
  date: string | null;
  /** Sections in the order they appear. */
  sections: Section[];
  /** Free-form lines before the first ### inside a release (rare). */
  preamble: string[];
}

interface Parsed {
  title: string | null; // `# Changelog`
  intro: string[]; // paragraphs before the first `##`
  releases: Release[];
}

function parseMarkdown(md: string): Parsed {
  const lines = md.replace(/\r\n/g, '\n').split('\n');
  const out: Parsed = { title: null, intro: [], releases: [] };

  let i = 0;
  let currentRelease: Release | null = null;
  let currentSection: Section | null = null;

  // Buffer paragraph lines until we know where they belong.
  let paraBuffer: string[] = [];
  function flushPara() {
    if (paraBuffer.length === 0) return;
    const text = paraBuffer.join(' ').trim();
    paraBuffer = [];
    if (!text) return;
    if (currentSection) {
      // Paragraph in the middle of a section — fold into the last bullet,
      // or treat as preamble of the release.
      const last = currentSection.items[currentSection.items.length - 1];
      if (last !== undefined) {
        currentSection.items[currentSection.items.length - 1] = last + ' ' + text;
      } else {
        currentRelease!.preamble.push(text);
      }
    } else if (currentRelease) {
      currentRelease.preamble.push(text);
    } else {
      out.intro.push(text);
    }
  }

  while (i < lines.length) {
    const raw = lines[i];
    const t = raw.trim();

    if (t === '') {
      flushPara();
      i++;
      continue;
    }

    // `# Title`
    if (t.startsWith('# ') && !t.startsWith('## ')) {
      flushPara();
      out.title = t.slice(2).trim();
      i++;
      continue;
    }

    // `## [version] - date`  OR  `## version`
    if (t.startsWith('## ')) {
      flushPara();
      const head = t.slice(3).trim();
      // Accept "[1.2.3] - 2026-01-01" or "1.2.3 - 2026-01-01" or "[Unreleased]"
      const m = head.match(/^\[?([^\]]+?)\]?(?:\s*[-–—]\s*(.+))?$/);
      const version = (m?.[1] ?? head).trim();
      const date = m?.[2]?.trim() || null;
      currentRelease = { version, date, sections: [], preamble: [] };
      currentSection = null;
      out.releases.push(currentRelease);
      i++;
      continue;
    }

    // `### Section`
    if (t.startsWith('### ')) {
      flushPara();
      const label = t.slice(4).trim();
      if (!currentRelease) {
        // Stray section before any version heading — synthesize one.
        currentRelease = { version: 'Unreleased', date: null, sections: [], preamble: [] };
        out.releases.push(currentRelease);
      }
      currentSection = { kind: classifySection(label), rawLabel: label, items: [] };
      currentRelease.sections.push(currentSection);
      i++;
      continue;
    }

    // `- item` (bullet)
    if (t.startsWith('- ')) {
      flushPara();
      let item = t.slice(2);
      i++;
      // Absorb continuation lines (indented under the bullet)
      while (i < lines.length) {
        const next = lines[i];
        const nt = next.trim();
        if (
          nt === '' ||
          nt.startsWith('- ') ||
          nt.startsWith('### ') ||
          nt.startsWith('## ') ||
          nt.startsWith('# ')
        )
          break;
        if (/^\s/.test(next)) {
          item += ' ' + nt;
          i++;
        } else break;
      }
      if (currentSection) {
        currentSection.items.push(item);
      } else if (currentRelease) {
        currentRelease.preamble.push('• ' + item);
      } else {
        out.intro.push('• ' + item);
      }
      continue;
    }

    // Plain paragraph line.
    paraBuffer.push(t);
    i++;
  }
  flushPara();

  return out;
}

// ── Inline rendering ─────────────────────────────────────────────────

function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let key = 0;
  let i = 0;
  while (i < text.length) {
    if (text[i] === '`') {
      const end = text.indexOf('`', i + 1);
      if (end !== -1) {
        nodes.push(
          <code
            key={key++}
            className="rounded bg-foreground/[0.06] px-1 py-0.5 text-[0.88em] font-mono text-foreground/85"
          >
            {text.slice(i + 1, end)}
          </code>
        );
        i = end + 1;
        continue;
      }
    }
    if (text[i] === '[') {
      const labelEnd = text.indexOf(']', i + 1);
      if (labelEnd !== -1 && text[labelEnd + 1] === '(') {
        const urlEnd = text.indexOf(')', labelEnd + 2);
        if (urlEnd !== -1) {
          const label = text.slice(i + 1, labelEnd);
          const url = text.slice(labelEnd + 2, urlEnd);
          nodes.push(
            <a
              key={key++}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-emerald-700 underline underline-offset-2 hover:text-emerald-800"
            >
              {label}
            </a>
          );
          i = urlEnd + 1;
          continue;
        }
      }
    }
    if (text.startsWith('**', i)) {
      const end = text.indexOf('**', i + 2);
      if (end !== -1) {
        nodes.push(
          <strong key={key++} className="font-semibold text-foreground">
            {text.slice(i + 2, end)}
          </strong>
        );
        i = end + 2;
        continue;
      }
    }
    if (text[i] === '*' && text[i + 1] !== '*' && text[i + 1] !== ' ') {
      const end = text.indexOf('*', i + 1);
      if (end !== -1 && text[end - 1] !== ' ') {
        nodes.push(
          <em key={key++} className="italic">
            {text.slice(i + 1, end)}
          </em>
        );
        i = end + 1;
        continue;
      }
    }
    let next = text.length;
    for (const ch of ['`', '[', '*']) {
      const idx = text.indexOf(ch, i);
      if (idx !== -1 && idx < next) next = idx;
    }
    nodes.push(text.slice(i, next));
    i = next;
  }
  return nodes;
}

// ── View ─────────────────────────────────────────────────────────────

function formatDate(iso: string): string {
  // Accept YYYY-MM-DD; render as "May 18, 2026".
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return iso;
  const [, y, mo, d] = m;
  const date = new Date(Date.UTC(Number(y), Number(mo) - 1, Number(d)));
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    timeZone: 'UTC',
  });
}

function isUnreleased(version: string): boolean {
  return /^unreleased$/i.test(version.trim());
}

function ReleaseCard({ release, isLatest }: { release: Release; isLatest: boolean }) {
  const unreleased = isUnreleased(release.version);
  const empty = release.sections.length === 0 && release.preamble.length === 0;

  return (
    <article
      className={`relative rounded-2xl overflow-hidden shadow-sm transition-shadow ${
        isLatest
          ? 'bg-gradient-to-br from-emerald-50/90 via-emerald-50/40 to-parchment-50 ring-1 ring-emerald-300/60 shadow-md'
          : unreleased
            ? 'bg-card/60 ring-1 ring-dashed ring-border/70'
            : 'bg-card ring-1 ring-black/[0.05]'
      }`}
    >
      {/* Header */}
      <header
        className={`flex items-baseline justify-between gap-3 px-5 pt-4 pb-3 ${
          isLatest ? 'border-b border-emerald-200/40' : 'border-b border-border/30'
        }`}
      >
        <div className="flex items-baseline gap-3 min-w-0">
          <h2
            className={`font-heading font-semibold tracking-tight ${
              unreleased ? 'text-foreground/60 text-lg' : 'text-2xl text-foreground'
            }`}
          >
            {unreleased ? 'Unreleased' : `v${release.version}`}
          </h2>
          {isLatest && (
            <span className="text-[10px] font-semibold tracking-[0.18em] uppercase text-emerald-700 bg-emerald-100 ring-1 ring-emerald-300/60 rounded-full px-2 py-0.5">
              Latest
            </span>
          )}
        </div>
        {release.date && (
          <time className="text-[11px] font-mono tabular-nums text-muted-foreground/70 shrink-0">
            {formatDate(release.date)}
          </time>
        )}
      </header>

      {/* Body */}
      <div className="px-5 py-4 space-y-4">
        {release.preamble.length > 0 && (
          <div className="space-y-2 text-[14px] text-foreground/75 leading-relaxed">
            {release.preamble.map((p, idx) => (
              <p key={idx}>{renderInline(p)}</p>
            ))}
          </div>
        )}

        {empty && (
          <p className="text-[13px] text-muted-foreground/60 italic">
            Nothing yet — track work in progress here.
          </p>
        )}

        {release.sections.map((section, idx) => {
          const style = SECTION_STYLES[section.kind];
          const Icon = style.icon;
          return (
            <section key={idx} className="space-y-2">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full text-[10px] font-semibold tracking-[0.14em] uppercase px-2 py-0.5 ring-1 ${style.badge} ${style.ring}`}
                >
                  <Icon className="w-3 h-3" />
                  {section.kind}
                </span>
                <div className="flex-1 h-px bg-border/30" />
              </div>
              <ul
                className={`list-disc pl-6 space-y-1.5 text-[14px] text-foreground/80 leading-relaxed ${style.accent}`}
              >
                {section.items.map((item, j) => (
                  <li key={j}>{renderInline(item)}</li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
    </article>
  );
}

export function renderChangelog(md: string): React.ReactNode {
  const parsed = parseMarkdown(md);

  // The "latest" badge goes on the first non-Unreleased release.
  const latestIdx = parsed.releases.findIndex((r) => !isUnreleased(r.version));

  return (
    <div className="space-y-5 animate-stagger">
      {parsed.intro.length > 0 && (
        <div className="space-y-2 text-[14px] text-foreground/70 leading-relaxed mb-2">
          {parsed.intro.map((p, idx) => (
            <p key={idx}>{renderInline(p)}</p>
          ))}
        </div>
      )}
      {parsed.releases.map((release, idx) => (
        <ReleaseCard key={idx} release={release} isLatest={idx === latestIdx} />
      ))}
      {parsed.releases.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-10">No release notes yet.</p>
      )}
    </div>
  );
}
