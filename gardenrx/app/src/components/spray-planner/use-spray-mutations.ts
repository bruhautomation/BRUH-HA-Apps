'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { createClient } from '@/lib/db/client';
import { calculateDose } from '@/lib/dose';
import { deductionFor } from '@/lib/inventory-deduct';
import { useToast } from '@/components/ui/toast';
import type { MixPlan } from '@/lib/mix-planner';

interface InventoryItem {
  id: number;
  product_id: number;
  quantity: number;
  unit: string;
  bottle_size: number | null;
  cost_dollars: number | null;
}

/** Minimal shape needed to remove — and later restore — a queued spray. */
export interface RemovableQueuedSpray {
  id: number;
  notes: string | null;
  products: Array<{ product_id: number; rate_applied: number | null; rate_unit?: string | null }>;
  crops: Array<{ crop_id: number }>;
}

export function useSprayMutations(inventoryData: InventoryItem[], sprayerGallons: number) {
  const router = useRouter();
  const { toast } = useToast();
  const [logging, setLogging] = useState<string | null>(null);

  async function queueSpray(
    plan: MixPlan,
    rates: Record<string, number>,
    notes: Record<string, string>
  ) {
    setLogging(plan.id);
    const supabase = createClient();

    const { data: queued, error: queueErr } = await supabase
      .from('queued_sprays')
      .insert({ notes: notes[plan.id] || null })
      .select()
      .single();

    if (queueErr || !queued) {
      console.error('Queue spray failed:', queueErr);
      toast({
        variant: 'error',
        title: "Couldn't queue spray",
        description: 'Nothing was saved — check your connection and try again.',
      });
      setLogging(null);
      return null;
    }

    const results = await Promise.all([
      ...plan.products.map((p) =>
        supabase.from('queued_spray_products').insert({
          queued_spray_id: queued.id,
          product_id: p.product.id,
          rate_applied: rates[`${plan.id}-${p.product.id}`] ?? p.suggestedRate,
          rate_unit: p.rateUnit,
        })
      ),
      ...plan.crops.map((c) =>
        supabase.from('queued_spray_crops').insert({
          queued_spray_id: queued.id,
          crop_id: c.id,
        })
      ),
    ]);

    if (results.some((r) => r.error)) {
      console.error(
        'Queue spray detail insert failed:',
        results.map((r) => r.error).filter(Boolean)
      );
      await rollbackQueued(queued.id);
      toast({
        variant: 'error',
        title: "Couldn't queue spray",
        description: "The spray wasn't saved — please try again.",
      });
      setLogging(null);
      return null;
    }

    setLogging(null);
    toast({
      variant: 'success',
      title: 'Spray queued',
      description: `${plan.crops.map((c) => c.name).join(', ')} · ${plan.products.map((p) => p.product.brand).join(' + ')}`,
    });
    router.refresh();
    return queued.id;
  }

  async function rollbackQueued(id: number) {
    const supabase = createClient();
    try {
      await supabase.from('queued_spray_products').delete().eq('queued_spray_id', id);
      await supabase.from('queued_spray_crops').delete().eq('queued_spray_id', id);
      await supabase.from('queued_sprays').delete().eq('id', id);
    } catch (e) {
      console.error('Rollback of queued spray failed:', e);
    }
  }

  async function rollbackEvent(id: number) {
    const supabase = createClient();
    try {
      await supabase.from('spray_event_products').delete().eq('spray_event_id', id);
      await supabase.from('spray_event_crops').delete().eq('spray_event_id', id);
      await supabase.from('spray_events').delete().eq('id', id);
    } catch (e) {
      console.error('Rollback of spray event failed:', e);
    }
  }

  /** Insert a spray event + its product/crop rows atomically (rolls back on partial failure). */
  async function insertSprayEvent(
    notes: string | null,
    volumeGallons: number | null,
    products: Array<{ product_id: number; rate_applied: number | null; rate_unit?: string }>,
    cropIds: number[]
  ): Promise<{ ok: boolean; eventId?: number }> {
    const supabase = createClient();
    const { data: event, error: eventErr } = await supabase
      .from('spray_events')
      .insert({ notes: notes || null, volume_gallons: volumeGallons })
      .select()
      .single();

    if (eventErr || !event) {
      console.error('Spray event insert failed:', eventErr);
      return { ok: false };
    }

    const results = await Promise.all([
      ...products.map((p) =>
        supabase.from('spray_event_products').insert({
          spray_event_id: event.id,
          product_id: p.product_id,
          rate_applied: p.rate_applied,
          ...(p.rate_unit ? { rate_unit: p.rate_unit } : {}),
        })
      ),
      ...cropIds.map((cropId) =>
        supabase.from('spray_event_crops').insert({ spray_event_id: event.id, crop_id: cropId })
      ),
    ]);

    if (results.some((r) => r.error)) {
      console.error(
        'Spray event detail insert failed:',
        results.map((r) => r.error).filter(Boolean)
      );
      await rollbackEvent(event.id);
      return { ok: false };
    }

    return { ok: true, eventId: event.id };
  }

  /** Best-effort side effects after a successful log: clear overlapping queued sprays + deduct stock. */
  async function applyPostLogSideEffects(
    cropIds: number[],
    products: Array<{ product_id: number; rate_applied: number | null; rate_unit: string }>
  ) {
    const supabase = createClient();
    try {
      const { data: queuedSprays } = await supabase.from('queued_sprays').select('id');
      if (queuedSprays) {
        const { data: allQCrops } = await supabase
          .from('queued_spray_crops')
          .select('queued_spray_id, crop_id');
        for (const qs of queuedSprays) {
          const qCropIds = (allQCrops ?? [])
            .filter((qc) => qc.queued_spray_id === qs.id)
            .map((qc) => qc.crop_id);
          if (cropIds.some((id) => qCropIds.includes(id))) {
            await supabase.from('queued_sprays').delete().eq('id', qs.id);
          }
        }
      }

      for (const p of products) {
        if (p.rate_applied == null) continue;
        const dose = calculateDose(p.rate_applied, p.rate_unit, sprayerGallons);
        const { data: invItems } = await supabase
          .from('treatment_inventory')
          .select('*')
          .eq('product_id', p.product_id);
        if (invItems && invItems.length > 0) {
          const inv = invItems[0];
          const deduct = deductionFor(dose, inv.unit);
          if (deduct !== null) {
            const newQty = Math.max(0, (inv.quantity ?? 0) - deduct);
            await supabase
              .from('treatment_inventory')
              .update({ quantity: newQty, updated_at: new Date().toISOString() })
              .eq('id', inv.id);
          }
        }
      }
    } catch (e) {
      // Side effects are non-critical — the spray is already logged. Don't fail the action.
      console.error('Post-log side effects failed:', e);
    }
  }

  async function logMix(
    plan: MixPlan,
    rates: Record<string, number>,
    notes: Record<string, string>,
    volumeGallons?: number
  ) {
    setLogging(plan.id);

    const products = plan.products.map((p) => ({
      product_id: p.product.id,
      rate_applied: rates[`${plan.id}-${p.product.id}`] ?? p.suggestedRate,
      rate_unit: p.rateUnit,
    }));
    const cropIds = plan.crops.map((c) => c.id);

    const { ok } = await insertSprayEvent(
      notes[plan.id] || null,
      volumeGallons ?? sprayerGallons,
      products,
      cropIds
    );

    if (!ok) {
      toast({
        variant: 'error',
        title: "Couldn't log spray",
        description: 'Nothing was saved — check your connection and try again.',
      });
      setLogging(null);
      return false;
    }

    await applyPostLogSideEffects(cropIds, products);

    setLogging(null);
    toast({
      variant: 'success',
      title: 'Spray logged',
      description: `${plan.crops.map((c) => c.name).join(', ')} · coverage updated.`,
    });
    router.refresh();
    return true;
  }

  async function saveQueuedEdit(
    id: number,
    editProducts: number[],
    editRates: Record<number, number>,
    editNotes: string
  ) {
    setLogging(`edit-${id}`);
    const supabase = createClient();

    const { error: updateErr } = await supabase
      .from('queued_sprays')
      .update({ notes: editNotes || null })
      .eq('id', id);
    if (updateErr) {
      console.error('Queued edit failed:', updateErr);
      toast({ variant: 'error', title: "Couldn't save changes", description: 'Please try again.' });
      setLogging(null);
      return;
    }

    // Preserve rate_unit from existing rows so edits don't silently reset it
    // to the column default ("fl oz/gal").
    const { data: existing } = await supabase
      .from('queued_spray_products')
      .select('product_id, rate_unit')
      .eq('queued_spray_id', id);
    const existingUnits = new Map<number, string>(
      (existing ?? []).map((r) => [r.product_id, r.rate_unit])
    );

    await supabase.from('queued_spray_products').delete().eq('queued_spray_id', id);
    const results = await Promise.all(
      editProducts.map((pid) => {
        const rateUnit = existingUnits.get(pid);
        return supabase.from('queued_spray_products').insert({
          queued_spray_id: id,
          product_id: pid,
          rate_applied: editRates[pid] ?? null,
          ...(rateUnit ? { rate_unit: rateUnit } : {}),
        });
      })
    );

    setLogging(null);
    if (results.some((r) => r.error)) {
      console.error(
        'Queued edit product insert failed:',
        results.map((r) => r.error).filter(Boolean)
      );
      toast({
        variant: 'error',
        title: "Some changes didn't save",
        description: 'Reopen the spray to check it.',
      });
    } else {
      toast({ variant: 'success', title: 'Spray updated' });
    }
    router.refresh();
  }

  async function removeQueuedSpray(spray: RemovableQueuedSpray) {
    setLogging(`remove-${spray.id}`);
    const supabase = createClient();
    const { error } = await supabase.from('queued_sprays').delete().eq('id', spray.id);
    setLogging(null);

    if (error) {
      console.error('Remove queued spray failed:', error);
      toast({ variant: 'error', title: "Couldn't remove spray", description: 'Please try again.' });
      return;
    }

    toast({
      variant: 'info',
      title: 'Queued spray removed',
      action: { label: 'Undo', onClick: () => restoreQueuedSpray(spray) },
    });
    router.refresh();
  }

  async function restoreQueuedSpray(spray: RemovableQueuedSpray) {
    const supabase = createClient();
    const { data: queued, error } = await supabase
      .from('queued_sprays')
      .insert({ notes: spray.notes })
      .select()
      .single();

    if (error || !queued) {
      console.error('Restore queued spray failed:', error);
      toast({
        variant: 'error',
        title: "Couldn't restore spray",
        description: 'Please re-create it.',
      });
      return;
    }

    await Promise.all([
      ...spray.products.map((p) =>
        supabase.from('queued_spray_products').insert({
          queued_spray_id: queued.id,
          product_id: p.product_id,
          rate_applied: p.rate_applied,
          ...(p.rate_unit ? { rate_unit: p.rate_unit } : {}),
        })
      ),
      ...spray.crops.map((c) =>
        supabase
          .from('queued_spray_crops')
          .insert({ queued_spray_id: queued.id, crop_id: c.crop_id })
      ),
    ]);

    toast({ variant: 'success', title: 'Spray restored' });
    router.refresh();
  }

  async function logQueuedSpray(qs: {
    id: number;
    notes: string | null;
    products: Array<{ product_id: number; rate_applied: number | null; rate_unit?: string | null }>;
    crops: Array<{ crop_id: number }>;
  }) {
    setLogging(`queued-${qs.id}`);

    const products = qs.products.map((p) => ({
      product_id: p.product_id,
      rate_applied: p.rate_applied,
      rate_unit: p.rate_unit ?? undefined,
    }));
    const cropIds = qs.crops.map((c) => c.crop_id);

    const { ok } = await insertSprayEvent(qs.notes, sprayerGallons, products, cropIds);

    if (!ok) {
      toast({
        variant: 'error',
        title: "Couldn't log spray",
        description: 'Nothing was saved — the queued spray is unchanged. Try again.',
      });
      setLogging(null);
      return;
    }

    const supabase = createClient();
    const { error: delErr } = await supabase.from('queued_sprays').delete().eq('id', qs.id);
    if (delErr) console.error('Clearing queued spray after log failed:', delErr);

    await applyPostLogSideEffects(
      cropIds,
      products.map((p) => ({ ...p, rate_unit: p.rate_unit ?? 'fl oz/gal' }))
    );

    setLogging(null);
    toast({ variant: 'success', title: 'Spray logged', description: 'Coverage updated.' });
    router.refresh();
  }

  return {
    logging,
    queueSpray,
    logMix,
    saveQueuedEdit,
    removeQueuedSpray,
    restoreQueuedSpray,
    logQueuedSpray,
  };
}
