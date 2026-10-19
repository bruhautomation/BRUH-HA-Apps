import type { DoseResult } from '@/lib/dose';

/**
 * How much of an inventory item one logged spray uses, in the unit the item is
 * tracked in. Weight units assume water-equivalent density; packets are not
 * deducted at all. Shared by the spray planner and the Home Assistant service
 * that logs a queued spray, so the two cannot disagree about a bottle.
 */
export function deductionFor(dose: DoseResult, inventoryUnit: string): number | null {
  switch (inventoryUnit) {
    case 'mL':
      return dose.mL;
    case 'tbsp':
      return dose.tbsp;
    case 'tsp':
      return dose.tsp;
    case 'gal':
      return dose.flOz / 128;
    case 'qt':
      return dose.flOz / 32;
    case 'pt':
      return dose.flOz / 16;
    case 'lb':
      return dose.flOz / 16;
    case 'g':
      return dose.mL;
    case 'packets':
      return null;
    default:
      return dose.flOz;
  }
}
