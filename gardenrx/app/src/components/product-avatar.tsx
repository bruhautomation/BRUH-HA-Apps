'use client';

import { useState } from 'react';
import { Bug, Leaf, ShieldHalf, Droplets, SprayCan, type LucideIcon } from 'lucide-react';
import type { AvatarType } from '@/lib/product-visual';
import { withBase } from '@/lib/base-path';

/**
 * ProductAvatar — one consistent product visual used everywhere a product
 * appears (Treatments list, product detail, Inventory, mix planner). Shows the
 * real label photo when we have one; otherwise a clean, type-colored icon so
 * the catalog always feels intentional and unified — never a broken image.
 *
 * Note: the `avatarTypeFor` helper lives in `@/lib/product-visual` (no
 * "use client") so server components can call it too.
 */

const TYPE_STYLE: Record<AvatarType, { tile: string; icon: LucideIcon; fg: string }> = {
  fungicide: { tile: 'bg-violet-50 ring-violet-200/60', icon: ShieldHalf, fg: 'text-violet-600' },
  insecticide: { tile: 'bg-sky-50 ring-sky-200/60', icon: Bug, fg: 'text-sky-600' },
  herbicide: { tile: 'bg-emerald-50 ring-emerald-200/60', icon: Leaf, fg: 'text-emerald-600' },
  bactericide: { tile: 'bg-teal-50 ring-teal-200/60', icon: Droplets, fg: 'text-teal-600' },
  combo: { tile: 'bg-fuchsia-50 ring-fuchsia-200/60', icon: SprayCan, fg: 'text-fuchsia-600' },
};

export function ProductAvatar({
  productId,
  type,
  brand,
  imageUrl,
  className = 'w-11 h-11',
  rounded = 'rounded-xl',
  iconClassName = 'w-5 h-5',
}: {
  productId: number;
  /** Dominant ingredient type, or "combo" for multi-ingredient products. */
  type?: AvatarType | string | null;
  brand?: string;
  /** Remote image URL (e.g. a web-sourced label); used when there's no bundled photo. */
  imageUrl?: string | null;
  className?: string;
  rounded?: string;
  iconClassName?: string;
}) {
  const [failed, setFailed] = useState(false);
  const [prevId, setPrevId] = useState(productId);
  if (productId !== prevId) {
    setPrevId(productId);
    setFailed(false);
  } // retry photo for a new product
  const style = TYPE_STYLE[type as AvatarType] ?? TYPE_STYLE.combo;

  if (failed) {
    const Icon = style.icon;
    return (
      <div
        className={`${className} ${rounded} shrink-0 ring-1 ${style.tile} flex items-center justify-center`}
        aria-hidden="true"
      >
        <Icon className={`${iconClassName} ${style.fg}`} />
      </div>
    );
  }

  return (
    <img
      src={withBase(imageUrl || `/images/products/${productId}.jpg`)}
      alt={brand ?? ''}
      loading="lazy"
      decoding="async"
      className={`${className} ${rounded} shrink-0 object-cover ring-1 ring-black/[0.06] bg-paper-2`}
      onError={() => setFailed(true)}
    />
  );
}
