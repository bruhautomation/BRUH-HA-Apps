# GardenRX

## Setting up

1. Install the add-on and start it. **GardenRX** appears in the sidebar.
2. Restart Home Assistant once, so it loads the `gardenrx` integration the
   add-on just installed.
3. Under **Settings → Devices & services**, GardenRX is waiting under
   *Discovered*. Press **Add**. The sensors, services and cards are now there.

The first start loads the product and label catalog. Your own crops,
varieties, sprays, harvests and stock start empty: add crops on the **Crops**
page and products to **Inventory**, and the Today page fills in from there.

## Where the data is

Everything is in one file, `gardenrx.db`, in the add-on's own data folder.
It is included in Home Assistant backups and restored with them; there is no
database server to run. The catalog is only ever *added* to on an update — a
product you edited keeps your edit.

## Location

Forecasts, rainfall and the time of day use the latitude, longitude and time
zone set in **Settings → System → General**. Turn off *Use Home Assistant's
location* to use the location built into GardenRX instead.

## Sensors

| Sensor | State | Attributes the cards read |
|---|---|---|
| Harvest this year | pounds picked this calendar year | `by_crop`, `recent` (each pick with its `id`), `crops` (with varieties), `total_value` |
| Harvest value this year | dollars, at each crop's $/lb | |
| Last spray | the date | `days_ago`, `products`, `crops`, `queued`, `phi` |
| Queued sprays | how many | `queued` (each with its `id`) |
| Crops in a pre-harvest interval | how many | `crops` (days left, the date it clears, the product) |
| Treatments running low | how many are at 20% or less | `items` (every product in stock) |

A count is valued with the crop's *average weight each* and its $/lb, the same
as the Harvest page.

## Services

- **`gardenrx.log_harvest`** — `crop` (name, or part of one, or id),
  `weight`, and optionally `variety`, `unit` (`lb`, `oz`, `kg`, `g`, `ct`),
  `date` and `notes`. A pick inside a pre-harvest interval is saved, and the
  response's `phi_warning` says so.
- **`gardenrx.delete_harvest`** — `id`.
- **`gardenrx.complete_queued_spray`** — `id`, and optionally
  `volume_gallons` and `date`. Logs the spray, removes it from the queue and
  takes what it used out of inventory, exactly as **Log this spray** on the
  Spray page does.
- **`gardenrx.delete_queued_spray`** — `id`.
- **`gardenrx.refresh`** — read the garden now instead of at the next poll.

Every service answers with what it did (call it with *response* in an
automation or script). A refusal — a crop nobody is called, a spray already
logged — is an error carrying the reason.

```yaml
action: gardenrx.log_harvest
data:
  crop: Apples
  variety: Liberty
  weight: 4.5
  unit: lb
response_variable: picked
```

## Cards

The integration loads the cards on every dashboard; there is no resource to
add.

```yaml
type: custom:gardenrx-harvest-card     # options: title, show_form, crops, recent
type: custom:gardenrx-spray-card       # options: title, show_queue, show_phi, volume_gallons
type: custom:gardenrx-inventory-card   # options: title, max_items, low_only
```

Each card also takes `entity:` to point at a sensor by id; without it, it
finds the GardenRX sensor itself.

Presses that change the record — **Delete** on a pick, **Mark sprayed** and
**Remove** on a queued spray — take two taps, the second within four seconds.

### Morph

When Morph is installed, the add-on copies the cards to `/config/morph/cards`.
In Morph's `dashboard.yaml` they are `custom:morph-gardenrx-harvest`,
`custom:morph-gardenrx-spray` and `custom:morph-gardenrx-inventory`, drawn in
Morph's own colours and fonts.

## Options

- **Home Assistant integration** — install the `gardenrx` integration.
- **Install the Morph cards** — copy the cards into Morph.
- **Use Home Assistant's location** — see *Location*.
- **Log level** — how much the add-on logs while it starts.
