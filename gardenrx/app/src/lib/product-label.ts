/**
 * Treatment-context product display: brand followed by active ingredient(s)
 * in parentheses. Used anywhere a product appears in a spray/mix/history UI.
 */
export function productLabel(
  brand: string,
  ingredients: ReadonlyArray<{ name: string }> | null | undefined
): string {
  if (!ingredients || ingredients.length === 0) return brand;
  const names = ingredients.map((i) => i.name).join(' + ');
  return `${brand} (${names})`;
}
