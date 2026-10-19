import { createClient } from '@/lib/db/server';
import { GlobalSearch } from '@/components/global-search';

export async function SearchWrapper() {
  const supabase = await createClient();

  const { data: _products } = await supabase
    .from('products')
    .select('id, brand, formulation, concentration')
    .order('brand');
  const { data: _crops } = await supabase
    .from('crops')
    .select('id, name, crop_group_id')
    .eq('is_active', true);
  const { data: _groups } = await supabase.from('crop_groups').select('id, name');

  const products = (_products ?? []) as Array<{
    id: number;
    brand: string;
    formulation: string | null;
    concentration: string | null;
  }>;
  const crops = (_crops ?? []) as Array<{ id: number; name: string; crop_group_id: number | null }>;
  const cropGroups = (_groups ?? []) as Array<{ id: number; name: string }>;

  return <GlobalSearch products={products} crops={crops} cropGroups={cropGroups} />;
}
