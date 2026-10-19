import { createClient } from '@/lib/db/server';
import { fetchVarieties, fetchCrops, fetchCropGroups } from '@/lib/queries';
import { GardenMap } from '@/components/garden-map';

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
    <div className="page">
      <div className="section-title">
        <h2>Garden Map</h2>
        <span className="meta">Plan your space</span>
      </div>
      <div className="mx-auto max-w-4xl">
        <GardenMap
          zones={zones ?? []}
          regions={regions ?? []}
          templates={templates ?? []}
          varieties={varieties}
          crops={crops}
          cropGroups={cropGroups}
        />
      </div>
    </div>
  );
}
