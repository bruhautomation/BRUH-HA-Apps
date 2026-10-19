import { describe, it, expect, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import type { Crop } from '@/lib/database.types';
import { HarvestCharts } from '@/components/harvest-charts';

afterEach(cleanup);

const crop = (id: number, name: string) => ({ id, name }) as unknown as Crop;

/** Twelve crops — comfortably past the eight the chart used to cap at — with a
 *  couple that resolve to the same palette entry and a couple the palette does
 *  not know at all (both of which used to land on one generic green). */
const NAMES = [
  'Blackberries',
  'Raspberries',
  'Blueberries',
  'Squash',
  'Tomatoes',
  'Cucumbers',
  'Zucchini',
  'Cantaloupe',
  'Peppers',
  'Tomatillos', // same palette key as Tomatoes
  'Sunchokes', // unknown to the palette → generic
  'Salsify', // unknown to the palette → generic
];

const DATES = ['2026-05-01', '2026-05-08', '2026-05-15'];

function fixture(names = NAMES, priced = true) {
  const byCrop = names.map((name, i) => ({
    crop: crop(i + 1, name),
    totalLb: (names.length - i) * 2,
    value: priced ? (names.length - i) * 3 : 0,
    picks: 3,
  }));
  const events = names.flatMap((_, i) =>
    DATES.map((date) => ({
      date,
      lb: (names.length - i) * 2 * (1 / 3),
      value: priced ? (names.length - i) * 3 * (1 / 3) : 0,
      cropId: i + 1,
    }))
  );
  return { byCrop, events };
}

/** Switch the cumulative trend to its stacked by-crop view. */
function showByCrop() {
  fireEvent.click(screen.getByRole('tab', { name: 'By crop' }));
}

/** Fills of the stacked bands in the trend chart (not the crop avatars). */
const bandFills = (c: HTMLElement) =>
  [...c.querySelectorAll('svg[viewBox="0 0 320 90"] path[fill]')]
    .map((p) => p.getAttribute('fill')!)
    .filter((f) => f !== 'none' && !f.startsWith('url('));

describe('HarvestCharts by-crop breakdown', () => {
  it('gives every crop its own legend row — no "other" lump', () => {
    const { byCrop, events } = fixture();
    render(<HarvestCharts byCrop={byCrop} events={events} />);
    showByCrop();

    for (const name of NAMES) expect(screen.getByText(new RegExp(name))).toBeInTheDocument();
    expect(screen.getByText(`${NAMES.length} crops`)).toBeInTheDocument();
    expect(screen.queryByText('Picks with no crop')).not.toBeInTheDocument();
  });

  it('stacks one band per crop, each a distinguishable color', () => {
    const { byCrop, events } = fixture();
    const { container } = render(<HarvestCharts byCrop={byCrop} events={events} />);
    showByCrop();

    const fills = bandFills(container);
    expect(fills).toHaveLength(NAMES.length);
    expect(new Set(fills).size).toBe(NAMES.length); // no two crops share a fill
  });

  it('keeps a crop that has no price — its weight is not swept into the tail', () => {
    const { byCrop, events } = fixture();
    // last crop is harvested but unpriced: weight, no value
    byCrop[byCrop.length - 1].value = 0;
    for (const e of events) if (e.cropId === byCrop.length) e.value = 0;

    render(<HarvestCharts byCrop={byCrop} events={events} />);
    showByCrop();

    const row = screen.getByText(new RegExp(NAMES[NAMES.length - 1])).closest('button')!;
    expect(within(row).getByText('$0.00')).toBeInTheDocument();
    expect(screen.queryByText('Picks with no crop')).not.toBeInTheDocument();
  });

  it('keeps a tail band only for picks logged against no crop', () => {
    const { byCrop, events } = fixture();
    events.push({ date: DATES[1], lb: 4, value: 6, cropId: null as unknown as number });

    const { container } = render(<HarvestCharts byCrop={byCrop} events={events} />);
    showByCrop();

    expect(screen.getByText('Picks with no crop')).toBeInTheDocument();
    expect(bandFills(container)).toHaveLength(NAMES.length + 1); // crops + the tail
  });

  it('shows no variety rows when no pick carries a variety', () => {
    const { byCrop, events } = fixture();
    render(<HarvestCharts byCrop={byCrop} events={events} />);
    expect(screen.queryAllByRole('listitem')).toHaveLength(0);
  });

  it('toggling a crop off drops its band from the stack', () => {
    const { byCrop, events } = fixture();
    const { container } = render(<HarvestCharts byCrop={byCrop} events={events} />);
    showByCrop();

    const before = bandFills(container).length;
    fireEvent.click(screen.getByText(new RegExp(NAMES[0])).closest('button')!);
    expect(bandFills(container)).toHaveLength(before - 1);
  });
});

/** Blueberries picked as two varieties plus one pick logged without one, and
 *  Squash with no variety data at all. Value is 2× the weight throughout, as
 *  it is in the app — a variety is priced by its crop. */
function varietyFixture() {
  const ev = (date: string, lb: number, cropId: number, varietyId: number | null) => ({
    date,
    lb,
    value: lb * 2,
    cropId,
    varietyId,
  });
  const byCrop = [
    {
      crop: crop(1, 'Blueberries'),
      totalLb: 9,
      value: 18,
      picks: 4,
      varieties: [
        { id: 11, name: 'Bluecrop', totalLb: 6, value: 12, picks: 2 },
        { id: 12, name: 'Duke', totalLb: 2, value: 4, picks: 1 },
      ],
    },
    { crop: crop(2, 'Squash'), totalLb: 10, value: 20, picks: 2, varieties: [] },
  ];
  const events = [
    ev(DATES[0], 3, 1, 11),
    ev(DATES[1], 3, 1, 11),
    ev(DATES[1], 2, 1, 12),
    ev(DATES[2], 1, 1, null),
    ev(DATES[0], 5, 2, null),
    ev(DATES[2], 5, 2, null),
  ];
  return { byCrop, events };
}

/** The variety rows rendered under one crop's bar. */
function varietyRowsFor(name: string) {
  const wrapper = screen.getByText(new RegExp(name)).closest('button')!.parentElement!;
  return within(wrapper)
    .queryAllByRole('listitem')
    .map((li) => li.textContent!.replace(/\s+/g, ' ').trim());
}

describe('HarvestCharts variety breakdown', () => {
  it('breaks a crop down by variety, biggest first, summing to the crop', () => {
    const { byCrop, events } = varietyFixture();
    render(<HarvestCharts byCrop={byCrop} events={events} />);

    expect(varietyRowsFor('Blueberries')).toEqual([
      'Bluecrop$12.006 lb',
      'Duke$4.002 lb',
      'No variety$2.001 lb',
    ]); // 12 + 4 + 2 = the crop's own $18.00
    const cropRow = screen.getByText(/Blueberries/).closest('button')!;
    expect(within(cropRow).getByText('$18.00')).toBeInTheDocument();
  });

  it('leaves a crop with no variety data alone', () => {
    const { byCrop, events } = varietyFixture();
    render(<HarvestCharts byCrop={byCrop} events={events} />);
    expect(varietyRowsFor('Squash')).toHaveLength(0);
  });

  it('keeps the variety rows out of the crop toggle', () => {
    const { byCrop, events } = varietyFixture();
    render(<HarvestCharts byCrop={byCrop} events={events} />);
    showByCrop();

    const li = screen.getByText('Bluecrop').closest('li')!;
    expect(li.closest('button')).toBeNull(); // a sub-row is text, not a control
    // …and toggling the crop still works with them in the tree
    fireEvent.click(screen.getByText(/Blueberries/).closest('button')!);
    expect(screen.getByText(/Blueberries/).closest('button')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
  });

  it('does not break out a crop that only has one variety', () => {
    // Blueberries picked as Bluecrop plus one pick logged without a variety:
    // the unassigned pick belongs to Bluecrop by elimination, so there is
    // nothing to break out and the crop's own row still carries all of it.
    const { byCrop, events } = varietyFixture();
    byCrop[0].varieties = [{ id: 11, name: 'Bluecrop', totalLb: 6, value: 12, picks: 2 }];
    const kept = events.filter((e) => e.varietyId !== 12);
    byCrop[0].totalLb = 7;
    byCrop[0].value = 14;
    byCrop[0].picks = 3;
    render(<HarvestCharts byCrop={byCrop} events={kept} />);

    expect(varietyRowsFor('Blueberries')).toHaveLength(0);
    expect(screen.queryByText('Bluecrop')).not.toBeInTheDocument();
    expect(screen.queryByText('No variety')).not.toBeInTheDocument();
    const cropRow = screen.getByText(/Blueberries/).closest('button')!;
    expect(within(cropRow).getByText('$14.00')).toBeInTheDocument(); // 12 + the loose 2
  });

  it('does not break out a second variety that has not been picked', () => {
    // Duke is on the crop but nothing has been harvested from it yet — one
    // variety with picks is still one variety.
    const { byCrop, events } = varietyFixture();
    const kept = events.filter((e) => e.varietyId !== 12);
    render(<HarvestCharts byCrop={byCrop} events={kept} />);

    expect(varietyRowsFor('Blueberries')).toHaveLength(0);
    expect(screen.queryByText('Duke')).not.toBeInTheDocument();
  });

  it('reports varieties in pounds when nothing is priced', () => {
    const { byCrop, events } = varietyFixture();
    for (const e of events) e.value = 0;
    for (const c of byCrop) {
      c.value = 0;
      for (const v of c.varieties ?? []) v.value = 0;
    }
    render(<HarvestCharts byCrop={byCrop} events={events} />);

    expect(varietyRowsFor('Blueberries')).toEqual(['Bluecrop6 lb', 'Duke2 lb', 'No variety1 lb']);
  });
});
