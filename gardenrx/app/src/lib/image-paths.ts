/**
 * Resolve image paths for crop problems and growth stages.
 * Images may have a __CC suffix indicating Creative Commons licensed (not public domain).
 * Filenames are slugified: "Apple Scab" -> "apple-scab"
 */

import { withBase } from '@/lib/base-path';

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

function groupSlug(groupName: string): string {
  return slugify(groupName);
}

/**
 * Get all possible image paths for a problem (PD and CC versions).
 * The component should try these in order with onError fallback.
 */
export function getProblemImagePaths(cropGroupName: string, problemName: string): string[] {
  const group = groupSlug(cropGroupName);
  const problem = slugify(problemName);
  return [
    withBase(`/images/problems/${group}/${problem}.jpg`),
    withBase(`/images/problems/${group}/${problem}__CC.jpg`),
  ];
}

export function getStageImagePaths(cropGroupName: string, stageSlug: string): string[] {
  const group = groupSlug(cropGroupName);
  return [
    withBase(`/images/stages/${group}/${stageSlug}.jpg`),
    withBase(`/images/stages/${group}/${stageSlug}__CC.jpg`),
  ];
}
