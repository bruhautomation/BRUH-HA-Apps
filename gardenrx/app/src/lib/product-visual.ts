/**
 * Pure helpers for product visuals — safe to import from BOTH server and client
 * components (no "use client"). Keep the React component in product-avatar.tsx.
 */

export type AvatarType = 'fungicide' | 'insecticide' | 'herbicide' | 'bactericide' | 'combo';

/** Pick the avatar type from a product's ingredient type list. */
export function avatarTypeFor(types: Array<string | null | undefined>): AvatarType {
  const distinct = Array.from(new Set(types.filter(Boolean))) as string[];
  if (distinct.length > 1) return 'combo';
  const t = distinct[0];
  if (t === 'fungicide' || t === 'insecticide' || t === 'herbicide' || t === 'bactericide')
    return t;
  return 'combo';
}
