import type { PhenologicalStage } from '@/lib/database.types';
import type { DailyForecast } from '@/lib/weather';
import { nextWake } from '@/lib/phenology';
import { STAGES_BY_GROUP, DEFAULT_STAGES } from '@/lib/growth-stages';
import { LOCATION } from '@/config/thresholds';

/** One line of Today's off-season section: a headline, why, and where it leads. */
export type SeasonLine = { key: string; title: string; detail: string; href: string };

/** A night at or below this (°F) is called out as a freeze. */
export const FREEZE_F = 32;

const MONTH_DAY = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });

/** "Oct 18" for a YYYY-MM-DD date (a calendar day, so no clock shift). */
function dayLabel(date: string): string {
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${date.slice(0, 10)}T12:00:00Z`));
}

/** "Oct 18" for a timestamp, on the garden's clock. */
function stampLabel(stamp: string): string {
  const t = Date.parse(stamp.includes('T') ? stamp : stamp.replace(' ', 'T') + 'Z');
  if (!Number.isFinite(t)) return dayLabel(stamp);
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: LOCATION.timezone,
  }).format(new Date(t));
}

function list(names: string[]): string {
  const uniq = [...new Set(names)];
  if (uniq.length <= 2) return uniq.join(' and ');
  return `${uniq.slice(0, 2).join(', ')} and ${uniq.length - 2} more`;
}

/**
 * What Today says while nothing is growing, from what the app already holds:
 * a freeze in the forecast, the season's typical task for each resting crop
 * group (the stage guide's own words) with when it wakes, the last spray and
 * the last pick. Each line is left out when its data is not there.
 */
export function offSeasonLines(input: {
  now: Date;
  crops: Array<{ name: string; groupName: string | null; stage: PhenologicalStage }>;
  daily: DailyForecast[];
  lastSpray: { date: string; products: string[]; crops: string[] } | null;
  lastPick: { at: string; crop: string; weight: number; unit: string } | null;
}): SeasonLine[] {
  const { now, crops, daily, lastSpray, lastPick } = input;
  const out: SeasonLine[] = [];

  const cold = daily
    .slice(0, 7)
    .filter((d) => typeof d.tempLow === 'number' && d.tempLow <= FREEZE_F)
    .sort((a, b) => a.tempLow - b.tempLow)[0];
  if (cold) {
    const day = new Intl.DateTimeFormat('en-US', { weekday: 'long', timeZone: 'UTC' }).format(
      new Date(`${cold.date}T12:00:00Z`)
    );
    out.push({
      key: 'freeze',
      title: `Freeze ${day} night`,
      detail: `A low of ${Math.round(cold.tempLow)}° is forecast. Cover anything tender and drain hoses.`,
      href: '/weather',
    });
  }

  // One line per crop group and stage, in the order the crops are listed.
  const groups = new Map<
    string,
    { groupName: string | null; stage: PhenologicalStage; names: string[] }
  >();
  for (const c of crops) {
    const key = `${c.groupName ?? ''}|${c.stage}`;
    const g = groups.get(key) ?? { groupName: c.groupName, stage: c.stage, names: [] };
    g.names.push(c.name);
    groups.set(key, g);
  }
  for (const [key, g] of [...groups].slice(0, 2)) {
    const stages = (g.groupName && STAGES_BY_GROUP[g.groupName]) || DEFAULT_STAGES;
    const info = stages.find((s) => s.stage === g.stage);
    if (!info) continue;
    const wake = nextWake(g.groupName, now);
    const wakeInfo = wake ? stages.find((s) => s.stage === wake.stage) : null;
    const wakeOn = wake ? MONTH_DAY.format(new Date(now.getTime() + wake.daysAway * 86400000)) : '';
    out.push({
      key: `task-${key}`,
      title: `${list(g.names)} · ${info.label}`,
      detail:
        info.description +
        (wake && wakeInfo ? ` ${wakeInfo.label} is typically around ${wakeOn}.` : ''),
      href: '/crops',
    });
  }

  if (lastSpray) {
    out.push({
      key: 'spray',
      title: `Last spray · ${dayLabel(lastSpray.date)}`,
      detail:
        (lastSpray.products.length ? list(lastSpray.products) : 'A spray') +
        (lastSpray.crops.length ? ` on ${list(lastSpray.crops)}` : '') +
        '.',
      href: '/history',
    });
  }

  if (lastPick) {
    const w = Math.round(lastPick.weight * 10) / 10;
    out.push({
      key: 'pick',
      title: `Last pick · ${stampLabel(lastPick.at)}`,
      detail: `${lastPick.crop}, ${w} ${lastPick.unit}.`,
      href: '/harvest',
    });
  }

  return out;
}
