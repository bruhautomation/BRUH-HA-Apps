package com.bruhautomation.sight;

import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.format.NamedTextColor;
import net.kyori.adventure.text.format.TextColor;
import net.kyori.adventure.text.format.TextDecoration;
import org.bukkit.Bukkit;
import org.bukkit.Color;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.NamespacedKey;
import org.bukkit.entity.Allay;
import org.bukkit.entity.Display;
import org.bukkit.entity.Entity;
import org.bukkit.entity.Player;
import org.bukkit.entity.TextDisplay;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.block.Action;
import org.bukkit.event.player.PlayerInteractEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.BookMeta;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.persistence.PersistentDataType;
import org.bukkit.util.Vector;

import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.HashMap;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;

/**
 * What the companion is thinking, shown where it is not in the way.
 *
 * <ul>
 *   <li><b>The bubble</b>: a small text display that only the player it is
 *   working for can see, floating over the companion's allay when it is
 *   near and otherwise up and to the side of them — never in the middle of
 *   the screen, never in chat. One line for what it is doing now, one for
 *   each job with its percent. It goes a few seconds after the work ends,
 *   and a quick "thinking" that ends fast never shows at all.</li>
 *   <li><b>The journal</b>: a book named after the companion. Using it opens
 *   the whole stream — what is going on now, every job, and the recent steps,
 *   newest first — and changes nothing.</li>
 * </ul>
 *
 * The panel posts each step ({@code POST /v1/thought}); nothing here is
 * saved with the world (the display is not persistent) and nothing here
 * changes a block.
 */
final class Thoughts implements Listener {

    static final int LOG_MAX = 60;
    static final long THINK_DELAY_MS = 2500;   // a "thinking" this short never shows
    static final long LINGER_MS = 4000;        // a finished line stays this long
    static final long STALE_MS = 120_000;      // a line nobody updated is dropped
    static final int LINE_CHARS = 48;
    static final int BUBBLE_LINES = 4;
    static final double ALLAY_NEAR = 16.0;
    static final DateTimeFormatter CLOCK = DateTimeFormatter.ofPattern("HH:mm");

    static final class Line {
        String key;
        String title;
        String text;
        String state;        // thinking | working | done | failed
        Integer percent;
        long since;
        long updated;
    }

    static final class Mind {
        final Map<String, Line> active = new LinkedHashMap<>();
        final Deque<String[]> log = new ArrayDeque<>();   // {epoch seconds, key, text}
        String name = "brAIn";
        TextColor colour = NamedTextColor.AQUA;
        UUID display;
    }

    private final BruhSight plugin;
    private final NamespacedKey journalKey;
    private final Map<UUID, Mind> minds = new HashMap<>();

    Thoughts(BruhSight plugin) {
        this.plugin = plugin;
        this.journalKey = new NamespacedKey(plugin, "journal");
    }

    void start() {
        Bukkit.getPluginManager().registerEvents(this, plugin);
        Bukkit.getScheduler().runTaskTimer(plugin, this::tick, 20L, 4L);
    }

    void stop() {
        for (Mind m : minds.values()) {
            removeDisplay(m);
        }
        minds.clear();
    }

    // -- from the panel (on the server thread) --------------------------------

    static String str(JsonObject o, String k, String dflt) {
        JsonElement e = o.get(k);
        return e == null || e.isJsonNull() ? dflt : e.getAsString();
    }

    static String clip(String s, int n) {
        String t = s == null ? "" : String.join(" ", s.trim().split("\\s+"));
        return t.length() <= n ? t : t.substring(0, n - 1) + "…";
    }

    Map<String, Object> thought(JsonObject req) throws BruhSight.BadRequest {
        Player p = Bukkit.getPlayerExact(str(req, "player", ""));
        if (p == null) {
            return Map.of("shown", false, "why", "not online");
        }
        String key = clip(str(req, "key", "talk"), 24);
        String state = str(req, "state", "working").toLowerCase(Locale.ROOT);
        if (!List.of("thinking", "working", "done", "failed", "clear").contains(state)) {
            throw new BruhSight.BadRequest("state is thinking, working, done, failed or clear");
        }
        Mind m = minds.computeIfAbsent(p.getUniqueId(), u -> new Mind());
        String name = str(req, "name", null);
        if (name != null && !name.isBlank()) {
            m.name = clip(name, 16);
        }
        String colour = str(req, "colour", null);
        if (colour != null) {
            NamedTextColor c = NamedTextColor.NAMES.value(colour.toLowerCase(Locale.ROOT));
            if (c != null) {
                m.colour = c;
            }
        }
        long now = System.currentTimeMillis();
        if (state.equals("clear")) {
            m.active.remove(key);
            return Map.of("shown", true);
        }
        Line line = m.active.get(key);
        if (line == null) {
            line = new Line();
            line.key = key;
            line.since = now;
            m.active.put(key, line);
        }
        String title = str(req, "title", null);
        if (title != null) {
            line.title = clip(title, 28);
        }
        String text = clip(str(req, "text", ""), 160);
        if (!text.isEmpty()) {
            line.text = text;
            if (!text.equals(lastLogged(m, key))) {
                m.log.addFirst(new String[]{String.valueOf(now / 1000), key,
                        (line.title != null ? line.title + ": " : "") + text});
                while (m.log.size() > LOG_MAX) {
                    m.log.removeLast();
                }
            }
        }
        line.state = state;
        line.updated = now;
        JsonElement pct = req.get("percent");
        line.percent = pct == null || pct.isJsonNull() ? line.percent
                : Math.max(0, Math.min(100, pct.getAsInt()));
        return Map.of("shown", true);
    }

    private static String lastLogged(Mind m, String key) {
        for (String[] row : m.log) {
            if (row[1].equals(key)) {
                String t = row[2];
                int i = t.indexOf(": ");
                return i >= 0 ? t.substring(i + 2) : t;
            }
        }
        return null;
    }

    Map<String, Object> giveJournal(JsonObject req) {
        Player p = Bukkit.getPlayerExact(str(req, "player", ""));
        if (p == null) {
            return Map.of("given", false, "why", "not online");
        }
        String name = clip(str(req, "name", "Thoughts"), 32);
        for (ItemStack s : p.getInventory().getContents()) {
            if (isJournal(s)) {
                return Map.of("given", false, "why", "already has one");
            }
        }
        ItemStack book = new ItemStack(Material.BOOK);
        ItemMeta meta = book.getItemMeta();
        meta.displayName(Component.text(name).decoration(TextDecoration.ITALIC, false));
        meta.lore(List.of(Component.text("Use it to see what I'm thinking")
                .color(NamedTextColor.GRAY).decoration(TextDecoration.ITALIC, false)));
        meta.getPersistentDataContainer().set(journalKey, PersistentDataType.BYTE, (byte) 1);
        book.setItemMeta(meta);
        Map<Integer, ItemStack> left = p.getInventory().addItem(book);
        for (ItemStack s : left.values()) {
            p.getWorld().dropItem(p.getLocation(), s);
        }
        return Map.of("given", true);
    }

    boolean isJournal(ItemStack s) {
        if (s == null || s.getType() != Material.BOOK || !s.hasItemMeta()) {
            return false;
        }
        return s.getItemMeta().getPersistentDataContainer().has(journalKey, PersistentDataType.BYTE);
    }

    // -- the journal ---------------------------------------------------------

    @EventHandler
    public void onUse(PlayerInteractEvent e) {
        if (e.getAction() != Action.RIGHT_CLICK_AIR && e.getAction() != Action.RIGHT_CLICK_BLOCK) {
            return;
        }
        if (!isJournal(e.getItem())) {
            return;
        }
        e.setCancelled(true);
        e.getPlayer().openBook(journal(e.getPlayer()));
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent e) {
        Mind m = minds.remove(e.getPlayer().getUniqueId());
        if (m != null) {
            removeDisplay(m);
        }
    }

    ItemStack journal(Player p) {
        Mind m = minds.getOrDefault(p.getUniqueId(), new Mind());
        List<Component> pages = new ArrayList<>();
        Component now = Component.text(m.name + "\n").color(m.colour).decorate(TextDecoration.BOLD)
                .append(Component.text("Right now\n\n").color(NamedTextColor.DARK_GRAY)
                        .decoration(TextDecoration.BOLD, false));
        if (m.active.isEmpty()) {
            now = now.append(Component.text("Nothing — I'm free. Ask me anything in chat.")
                    .color(NamedTextColor.BLACK).decoration(TextDecoration.BOLD, false));
        }
        for (Line l : m.active.values()) {
            now = now.append(Component.text(mark(l) + " " + label(l) + "\n")
                    .color(NamedTextColor.BLACK).decoration(TextDecoration.BOLD, false));
        }
        pages.add(now);
        StringBuilder page = new StringBuilder();
        int lines = 0;
        ZoneId zone = ZoneId.systemDefault();
        for (String[] row : m.log) {
            String when = CLOCK.format(Instant.ofEpochSecond(Long.parseLong(row[0])).atZone(zone));
            String entry = when + " " + clip(row[2], 90) + "\n";
            int cost = 1 + entry.length() / 19;
            if (lines + cost > 13 && page.length() > 0) {
                pages.add(Component.text(page.toString()).color(NamedTextColor.BLACK));
                page.setLength(0);
                lines = 0;
                if (pages.size() >= 20) {
                    break;
                }
            }
            page.append(entry);
            lines += cost;
        }
        if (page.length() > 0 && pages.size() < 20) {
            pages.add(Component.text(page.toString()).color(NamedTextColor.BLACK));
        }
        ItemStack book = new ItemStack(Material.WRITTEN_BOOK);
        BookMeta meta = (BookMeta) book.getItemMeta();
        meta.setTitle(clip(m.name + "'s Thoughts", 32));
        meta.setAuthor(m.name);
        meta.addPages(pages.toArray(new Component[0]));
        book.setItemMeta(meta);
        return book;
    }

    private static String mark(Line l) {
        switch (l.state) {
            case "done":
                return "✔";
            case "failed":
                return "✘";
            case "thinking":
                return "…";
            default:
                return "▸";
        }
    }

    private static String label(Line l) {
        String body = l.text != null ? l.text : (l.state.equals("thinking") ? "thinking" : "working");
        String head = l.title != null ? l.title + ": " : "";
        String pct = l.percent != null && !l.state.equals("done") ? " (" + l.percent + "%)" : "";
        return head + body + pct;
    }

    // -- the bubble ------------------------------------------------------------

    private void tick() {
        long now = System.currentTimeMillis();
        Iterator<Map.Entry<UUID, Mind>> it = minds.entrySet().iterator();
        while (it.hasNext()) {
            Map.Entry<UUID, Mind> e = it.next();
            Mind m = e.getValue();
            m.active.values().removeIf(l ->
                    ((l.state.equals("done") || l.state.equals("failed")) && now - l.updated > LINGER_MS)
                            || now - l.updated > STALE_MS);
            Player p = Bukkit.getPlayer(e.getKey());
            List<Line> shown = new ArrayList<>();
            for (Line l : m.active.values()) {
                if (l.state.equals("thinking") && now - l.since < THINK_DELAY_MS) {
                    continue;
                }
                shown.add(l);
            }
            if (p == null || !p.isOnline() || shown.isEmpty()) {
                removeDisplay(m);
                continue;
            }
            Location at = anchor(p);
            TextDisplay d = m.display == null ? null : (TextDisplay) Bukkit.getEntity(m.display);
            if (d == null || !d.isValid() || !d.getWorld().equals(at.getWorld())) {
                removeDisplay(m);
                d = spawn(p, at);
                m.display = d.getUniqueId();
            } else if (d.getLocation().distanceSquared(at) > 0.0025) {
                d.teleport(at);
            }
            d.text(render(m, shown));
        }
    }

    private Location anchor(Player p) {
        Entity allay = null;
        double best = ALLAY_NEAR * ALLAY_NEAR;
        for (Entity e : p.getNearbyEntities(ALLAY_NEAR, ALLAY_NEAR / 2, ALLAY_NEAR)) {
            if (e instanceof Allay && e.getScoreboardTags().contains("bruh_companion")) {
                double d2 = e.getLocation().distanceSquared(p.getLocation());
                if (d2 < best) {
                    best = d2;
                    allay = e;
                }
            }
        }
        if (allay != null) {
            return allay.getLocation().add(0, 1.1, 0);
        }
        // Up and to the right of where they look, out of the middle of the screen.
        Location eye = p.getEyeLocation();
        Vector fwd = eye.getDirection().setY(0);
        if (fwd.lengthSquared() < 1e-6) {
            fwd = new Vector(0, 0, 1);
        }
        fwd.normalize();
        Vector right = new Vector(-fwd.getZ(), 0, fwd.getX());
        return eye.clone().add(fwd.multiply(3.2)).add(right.multiply(1.9)).add(0, 0.9, 0);
    }

    private TextDisplay spawn(Player owner, Location at) {
        return at.getWorld().spawn(at, TextDisplay.class, d -> {
            d.setPersistent(false);
            d.setVisibleByDefault(false);
            d.setBillboard(Display.Billboard.CENTER);
            d.setShadowed(false);
            d.setSeeThrough(false);
            d.setLineWidth(220);
            d.setBackgroundColor(Color.fromARGB(96, 0, 0, 0));
            d.setTransformation(new org.bukkit.util.Transformation(
                    new org.joml.Vector3f(), new org.joml.Quaternionf(),
                    new org.joml.Vector3f(0.55f, 0.55f, 0.55f), new org.joml.Quaternionf()));
            d.setTeleportDuration(3);
            d.addScoreboardTag("bruh_thought");
            owner.showEntity(plugin, d);
        });
    }

    private Component render(Mind m, List<Line> shown) {
        Component c = Component.text("✦ " + m.name).color(m.colour);
        int n = 0;
        for (Line l : shown) {
            if (n++ >= BUBBLE_LINES) {
                c = c.append(Component.text("\n+" + (shown.size() - BUBBLE_LINES) + " more — see the book")
                        .color(NamedTextColor.GRAY));
                break;
            }
            NamedTextColor col = l.state.equals("done") ? NamedTextColor.GREEN
                    : l.state.equals("failed") ? NamedTextColor.RED : NamedTextColor.WHITE;
            c = c.append(Component.text("\n" + mark(l) + " " + clip(label(l), LINE_CHARS)).color(col));
        }
        return c;
    }

    private void removeDisplay(Mind m) {
        if (m.display == null) {
            return;
        }
        Entity e = Bukkit.getEntity(m.display);
        if (e != null) {
            e.remove();
        }
        m.display = null;
    }
}
