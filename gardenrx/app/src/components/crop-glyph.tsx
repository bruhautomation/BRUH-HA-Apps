import { resolveCropIconKey, cropIconColor } from '@/components/crop-icon';

/**
 * Neutral, monochrome crop glyphs (handoff color rule: a crop tile is *identity,
 * not status* → neutral avatar + a crop-type glyph, never colored by category).
 * Ported from the design's CropGlyph set. For colored illustrations on their own
 * tiles, see crop-icon.tsx (used where identity-color is acceptable, e.g. detail
 * hero); for status-driven surfaces use this neutral avatar.
 */

export type GlyphKind =
  | 'apple'
  | 'pear'
  | 'cherry'
  | 'berry'
  | 'strawberry'
  | 'melon'
  | 'watermelon'
  | 'gourd'
  | 'pepper'
  | 'tomato'
  | 'leafy'
  | 'herb'
  | 'flower'
  | 'grass';

// crop-icon.tsx resolution key → neutral glyph kind
const ICON_KEY_TO_GLYPH: Record<string, GlyphKind> = {
  apple: 'apple',
  pear: 'pear',
  cherry: 'cherry',
  peach: 'cherry',
  blueberry: 'berry',
  blackberry: 'berry',
  raspberry: 'berry',
  grape: 'berry',
  strawberry: 'strawberry',
  melon: 'melon',
  watermelon: 'watermelon',
  cucumber: 'gourd',
  zucchini: 'gourd',
  squash: 'gourd',
  tomato: 'tomato',
  pepper: 'pepper',
  kale: 'leafy',
  lettuce: 'leafy',
  basil: 'herb',
  rosemary: 'herb',
  grass: 'grass',
  pawpaw: 'pear',
  rose: 'flower',
  peony: 'flower',
  loropetalum: 'flower',
  sprout: 'leafy',
};

export function resolveGlyphKind(name: string, group?: string | null): GlyphKind {
  return ICON_KEY_TO_GLYPH[resolveCropIconKey(name, group)] ?? 'leafy';
}

export function CropGlyph({
  kind,
  size = 22,
  className,
}: {
  kind: GlyphKind;
  size?: number;
  className?: string;
}) {
  const glyphs: Record<GlyphKind, React.ReactNode> = {
    apple: (
      <g>
        <path
          d="M12 8.2c-1.1-2-3.4-2.2-4.9-1.1C5.4 8.4 5 11 5.6 13.4 6.3 16.3 8.4 19 10.3 19c.7 0 1.2-.4 1.7-.4s1 .4 1.7.4c1.9 0 4-2.7 4.7-5.6.6-2.4.2-5-1.5-6.3-1.5-1.1-3.8-.9-4.9 1.1Z"
          fill="currentColor"
        />
        <path
          d="M12 8.2c.2-1.6 1.3-2.9 2.9-3.2"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path
          d="M13 6.4c1-1.3 2.6-1.5 3.6-.9.1 1.2-.7 2.5-2 2.8"
          fill="currentColor"
          opacity=".55"
        />
      </g>
    ),
    pear: (
      <g>
        <path
          d="M12 5.6c1.3 0 1.9 1.1 1.7 2.3-.2 1.1.3 1.7 1 2.6 1 1.2 1.8 2.6 1.8 4.2 0 2.4-2 4.3-4.5 4.3S7.5 17.1 7.5 14.7c0-1.6.8-3 1.8-4.2.7-.9 1.2-1.5 1-2.6-.2-1.2.4-2.3 1.7-2.3Z"
          fill="currentColor"
        />
        <path
          d="M12 5.6c.2-1 .9-1.8 1.9-2"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </g>
    ),
    cherry: (
      <g>
        <circle cx="8.5" cy="16" r="3.3" fill="currentColor" />
        <circle cx="15.5" cy="15.3" r="3.3" fill="currentColor" opacity=".7" />
        <path
          d="M8.7 12.7C9.5 9 12 6 16 5.5M15.6 12C15.8 9 16 6.5 16 5.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
        <path d="M16 5.5c1.4-.6 2.8-.3 3.5.6-.9.8-2.2 1-3.3.5" fill="currentColor" opacity=".55" />
      </g>
    ),
    berry: (
      <g>
        <circle cx="9" cy="14" r="2.4" fill="currentColor" />
        <circle cx="14" cy="13.4" r="2.4" fill="currentColor" opacity=".75" />
        <circle cx="11.4" cy="17.4" r="2.4" fill="currentColor" opacity=".6" />
        <circle cx="12" cy="10" r="2.2" fill="currentColor" opacity=".85" />
        <path
          d="M12 8V5.5M12 5.5c1-.9 2.3-1 3.2-.4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
        />
      </g>
    ),
    strawberry: (
      <g>
        <path
          d="M12 19c3 0 5.5-3 5.5-6.2 0-2-1.6-3.3-3.4-3.6C13 9 12.6 8.8 12 8.8s-1 .2-2.1.4C8.1 9.5 6.5 10.8 6.5 12.8 6.5 16 9 19 12 19Z"
          fill="currentColor"
        />
        <path
          d="M8.5 7.5c1-.7 2.3-.9 3.5-.6 1.2-.3 2.5-.1 3.5.6-.8.9-2 1.4-3.5 1.4S9.3 8.4 8.5 7.5Z"
          fill="currentColor"
          opacity=".55"
        />
        <g fill="var(--paper)">
          <circle cx="10" cy="13" r=".7" />
          <circle cx="13.4" cy="12.6" r=".7" />
          <circle cx="11.7" cy="15.4" r=".7" />
        </g>
      </g>
    ),
    melon: (
      <g>
        <circle cx="12" cy="13" r="7" fill="currentColor" />
        <path
          d="M12 6v14M7 8.5c2 2.5 2 6.5 0 9M17 8.5c-2 2.5-2 6.5 0 9"
          fill="none"
          stroke="var(--paper)"
          strokeWidth="1.2"
          opacity=".5"
        />
      </g>
    ),
    watermelon: (
      <g>
        {/* slice — red flesh below a flat top edge */}
        <path d="M4.5 9.5 A 7.5 7.5 0 0 0 19.5 9.5 Z" fill="currentColor" />
        {/* green rind along the curved edge */}
        <path
          d="M4.5 9.5 A 7.5 7.5 0 0 0 19.5 9.5"
          fill="none"
          stroke="#3f9a52"
          strokeWidth="2.2"
          strokeLinecap="round"
        />
        {/* seeds */}
        <g fill="#2f2a2a">
          <ellipse cx="9.6" cy="12" rx=".55" ry=".9" transform="rotate(-16 9.6 12)" />
          <ellipse cx="13.4" cy="11.7" rx=".55" ry=".9" transform="rotate(14 13.4 11.7)" />
          <ellipse cx="11.5" cy="14.3" rx=".55" ry=".9" />
        </g>
      </g>
    ),
    gourd: (
      <g>
        <path
          d="M14.5 6.3c-1.2.3-1.8 1.3-1.9 2.6-1.9.6-3.6 2.6-3.6 5.6 0 3 2 5 4.5 5s4.5-2 4.5-5c0-2.4-1.1-4.2-2.5-5.1.2-1 .9-1.4 1.8-1.5-.6-1.2-1.6-1.5-2.8-1.6Z"
          fill="currentColor"
        />
        <path
          d="M14.6 6.3c.6-1 1.7-1.4 2.8-1.1"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </g>
    ),
    pepper: (
      <g>
        <path
          d="M8 11c0 4 2 8 4.2 8 1 0 1.6-.7 2.3-.7.9 0 1.5 1 2.5.3 1.4-1 1.2-3.6-.3-5.6C15.4 11.3 13.6 10 11 10c-1.7 0-3 .4-3 1Z"
          fill="currentColor"
        />
        <path
          d="M11.5 10V8.2c0-1 .7-1.8 1.7-2 .8-.2 1.4-.9 1.4-1.7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </g>
    ),
    tomato: (
      <g>
        <circle cx="12" cy="13.5" r="6.3" fill="currentColor" />
        <path
          d="M12 7.2 10 5.5M12 7.2 14 5.5M12 7.2V5M9.2 7.6 12 9l2.8-1.4"
          fill="none"
          stroke="var(--leaf)"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
    ),
    leafy: (
      <g>
        <path
          d="M12 20c0-5-2-9-5.5-10.5C6 14 8 18 12 20ZM12 20c0-5 2-9 5.5-10.5C18 14 16 18 12 20ZM12 20c0-6 0-10 0-14"
          fill="currentColor"
          stroke="currentColor"
          strokeWidth="1.2"
          strokeLinejoin="round"
        />
      </g>
    ),
    herb: (
      <g>
        <path
          d="M12 20V7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
          strokeLinecap="round"
        />
        <path
          d="M12 11c-1.6 0-3-1-3.4-2.8C10.2 8 11.6 9 12 11ZM12 11c1.6 0 3-1 3.4-2.8C13.8 8 12.4 9 12 11ZM12 15c-1.6 0-3-1-3.4-2.8C10.2 12 11.6 13 12 15ZM12 15c1.6 0 3-1 3.4-2.8C13.8 12 12.4 13 12 15Z"
          fill="currentColor"
        />
      </g>
    ),
    flower: (
      <g>
        <g fill="currentColor">
          <ellipse cx="12" cy="6.5" rx="2" ry="3" />
          <ellipse cx="12" cy="17.5" rx="2" ry="3" />
          <ellipse cx="6.5" cy="12" rx="3" ry="2" />
          <ellipse cx="17.5" cy="12" rx="3" ry="2" />
        </g>
        <circle cx="12" cy="12" r="2.4" fill="var(--paper)" />
        <circle cx="12" cy="12" r="1.4" fill="currentColor" />
      </g>
    ),
    grass: (
      <g fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
        <path d="M7 20c0-4 0-7-1.5-9M10 20c0-5 .5-8 0-11M13.5 20c0-5 .5-8 1.5-11M17 20c0-4 .5-7 1.5-9" />
      </g>
    ),
  };
  return (
    <svg viewBox="0 0 24 24" width={size} height={size} className={className} aria-hidden="true">
      {glyphs[kind] ?? glyphs.leafy}
    </svg>
  );
}

/** Crop avatar — a soft tint of the crop's color + its representative glyph. */
export function CropAvatar({
  name,
  group,
  size = 42,
  className = '',
}: {
  name: string;
  group?: string | null;
  size?: number;
  className?: string;
}) {
  const kind = resolveGlyphKind(name, group);
  const color = cropIconColor(name, group);
  return (
    <div
      className={`grid shrink-0 place-items-center rounded-[11px] ${className}`}
      style={{
        width: size,
        height: size,
        background: `color-mix(in srgb, ${color} 16%, transparent)`,
        color,
      }}
      aria-hidden="true"
    >
      <CropGlyph kind={kind} size={Math.round(size * 0.6)} />
    </div>
  );
}
