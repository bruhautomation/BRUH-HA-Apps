import { createClient } from '@/lib/db/server';
import { fetchVarieties, fetchCrops, fetchCropGroups } from '@/lib/queries';
import { GardenMap } from '@/components/garden-map';
import { PageShell } from '@/components/ui/page-shell';

export const dynamic = 'force-dynamic';

export default async function GardenPage() {
  const supabase = await createClient();

  const [varieties, crops, cropGroups, { data: zones }, { data: regions }, { data: templates }] =
    await Promise.all([
      fetchVarieties(),
      fetchCrops(),
      fetchCropGroups(),
      supabase.from('garden_zones').select('*').order('created_at'),
      supabase.from('garden_regions').select('*'),
      supabase.from('garden_templates').select('*').order('name'),
    ]);

  return (
    <PageShell width="wide" title="Garden" meta="Plan your space">
      <GardenMap
        zones={zones ?? []}
        regions={regions ?? []}
        templates={templates ?? []}
        varieties={varieties}
        crops={crops}
        cropGroups={cropGroups}
      />
    </PageShell>
  );
}
