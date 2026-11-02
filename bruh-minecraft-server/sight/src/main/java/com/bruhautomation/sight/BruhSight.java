package com.bruhautomation.sight;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.bukkit.Bukkit;
import org.bukkit.ChunkSnapshot;
import org.bukkit.FluidCollisionMode;
import org.bukkit.Location;
import org.bukkit.Material;
import org.bukkit.World;
import org.bukkit.block.Block;
import org.bukkit.entity.Entity;
import org.bukkit.entity.LivingEntity;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.block.BlockBreakEvent;
import org.bukkit.event.block.BlockPlaceEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.inventory.ItemStack;
import org.bukkit.inventory.meta.ItemMeta;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.util.RayTraceResult;
import org.bukkit.util.Vector;

import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Deque;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;

/**
 * BRUH Sight: the live world, for the BRUH Minecraft panel.
 *
 * The panel used to know the world only through RCON replies and the region
 * files on disk, which the server writes minutes after a block changes — so
 * the companion could not see what had just been built, and an unsaved chunk
 * read as nothing at all. This plugin answers from the running server
 * instead, on loopback only, with a token the panel reads from this
 * plugin's folder:
 *
 * <ul>
 *   <li>{@code GET /v1/state} — every online player: position, facing, the
 *   block and the entity under their crosshair, what they hold and carry,
 *   what is around them, the blocks they just placed or broke.</li>
 *   <li>{@code POST /v1/blocks} — every block state in a box, from the chunks
 *   in memory (a saved chunk is loaded to read it; one never generated is
 *   said, not guessed).</li>
 *   <li>{@code GET /v1/health} — that it is here, and its version.</li>
 * </ul>
 *
 * It changes no block: every edit still goes through the panel's undoable
 * path. What it adds to the game is the companion's thoughts ({@link
 * Thoughts}): a bubble only the asking player sees, never saved with the
 * world, and a book that opens the whole stream. Reads of the world happen on the server thread
 * (block data is copied in chunk snapshots there and encoded off it).
 */
public final class BruhSight extends JavaPlugin implements Listener {

    static final int DEFAULT_PORT = 25591;
    static final int PORT_TRIES = 10;
    static final double REACH = 96.0;          // the spyglass's reach, in blocks
    static final double ENTITY_REACH = 32.0;
    static final double NEARBY = 24.0;
    static final int NEARBY_MAX = 24;
    static final int RECENT_MAX = 30;          // block changes kept per player
    static final int INVENTORY_MAX = 40;
    static final int BOX_MAX = 262_144;        // cells in one blocks read
    static final int CHUNK_LOADS_MAX = 256;    // saved chunks loaded for one read
    static final long SYNC_TIMEOUT_S = 10;

    private final Gson gson = new GsonBuilder().disableHtmlEscaping().create();
    private final Map<UUID, Deque<Map<String, Object>>> recent = new ConcurrentHashMap<>();
    private HttpServer http;
    private ExecutorService pool;
    private byte[] token;
    private Path endpoint;
    private Thoughts thoughts;

    @Override
    public void onEnable() {
        try {
            Files.createDirectories(getDataFolder().toPath());
            String secret = loadToken();
            token = secret.getBytes(StandardCharsets.UTF_8);
            int port = bind();
            endpoint = getDataFolder().toPath().resolve("endpoint.json");
            Map<String, Object> ep = new LinkedHashMap<>();
            ep.put("host", "127.0.0.1");
            ep.put("port", port);
            ep.put("token", secret);
            ep.put("version", getDescription().getVersion());
            ep.put("pid", ProcessHandle.current().pid());
            writeAtomically(endpoint, gson.toJson(ep));
            getServer().getPluginManager().registerEvents(this, this);
            thoughts = new Thoughts(this);
            thoughts.start();
            getLogger().info("Listening on 127.0.0.1:" + port + " for the BRUH Minecraft panel");
        } catch (IOException e) {
            getLogger().severe("Could not start: " + e.getMessage());
            getServer().getPluginManager().disablePlugin(this);
        }
    }

    @Override
    public void onDisable() {
        if (thoughts != null) {
            thoughts.stop();
        }
        if (http != null) {
            http.stop(0);
        }
        if (pool != null) {
            pool.shutdownNow();
        }
        if (endpoint != null) {
            try {
                Files.deleteIfExists(endpoint);
            } catch (IOException ignored) {
                // A stale file is harmless: the panel's call fails and it falls back.
            }
        }
    }

    // -- set-up --------------------------------------------------------------

    private String loadToken() throws IOException {
        Path file = getDataFolder().toPath().resolve("token");
        if (Files.isRegularFile(file)) {
            String t = Files.readString(file, StandardCharsets.UTF_8).trim();
            if (t.length() >= 32) {
                return t;
            }
        }
        byte[] raw = new byte[24];
        new SecureRandom().nextBytes(raw);
        StringBuilder sb = new StringBuilder();
        for (byte b : raw) {
            sb.append(String.format("%02x", b));
        }
        writeAtomically(file, sb.toString());
        return sb.toString();
    }

    private int bind() throws IOException {
        int first = getConfig().getInt("port", DEFAULT_PORT);
        IOException last = null;
        for (int i = 0; i < PORT_TRIES; i++) {
            try {
                http = HttpServer.create(
                        new InetSocketAddress(InetAddress.getLoopbackAddress(), first + i), 16);
                break;
            } catch (IOException e) {
                last = e;
                http = null;
            }
        }
        if (http == null) {
            throw last != null ? last : new IOException("no free port");
        }
        pool = Executors.newFixedThreadPool(3, r -> {
            Thread t = new Thread(r, "BruhSight-http");
            t.setDaemon(true);
            return t;
        });
        http.setExecutor(pool);
        http.createContext("/v1/health", ex -> serve(ex, "GET", () -> health()));
        http.createContext("/v1/state", ex -> serve(ex, "GET", () -> onMain(this::state)));
        http.createContext("/v1/blocks", ex -> serve(ex, "POST", () -> blocks(readBody(ex))));
        http.createContext("/v1/thought", ex -> serve(ex, "POST", () -> {
            JsonObject req = readBody(ex);
            return onMain(() -> thoughts.thought(req));
        }));
        http.createContext("/v1/focus", ex -> serve(ex, "POST", () -> {
            JsonObject req = readBody(ex);
            return onMain(() -> thoughts.focus(req));
        }));
        http.createContext("/v1/journal", ex -> serve(ex, "POST", () -> {
            JsonObject req = readBody(ex);
            return onMain(() -> thoughts.giveJournal(req));
        }));
        http.start();
        return http.getAddress().getPort();
    }

    private static void writeAtomically(Path file, String text) throws IOException {
        Path tmp = file.resolveSibling(file.getFileName() + ".tmp");
        Files.writeString(tmp, text, StandardCharsets.UTF_8);
        try {
            // The token is the panel's and the server's (both the minecraft user).
            Files.setPosixFilePermissions(tmp, java.nio.file.attribute.PosixFilePermissions.fromString("rw-------"));
        } catch (UnsupportedOperationException ignored) {
            // A filesystem without POSIX modes: loopback still keeps it off the LAN.
        }
        Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
    }

    // -- http ----------------------------------------------------------------

    interface Answer {
        Object get() throws Exception;
    }

    private void serve(HttpExchange ex, String method, Answer answer) throws IOException {
        int code = 200;
        Object body;
        try {
            String given = ex.getRequestHeaders().getFirst("X-Bruh-Token");
            if (given == null || !MessageDigest.isEqual(
                    given.getBytes(StandardCharsets.UTF_8), token)) {
                code = 401;
                body = Map.of("error", "unauthorized");
            } else if (!method.equals(ex.getRequestMethod())) {
                code = 405;
                body = Map.of("error", "method");
            } else {
                body = answer.get();
            }
        } catch (BadRequest e) {
            code = 400;
            body = Map.of("error", e.getMessage());
        } catch (Exception e) {
            Throwable cause = e instanceof java.util.concurrent.ExecutionException && e.getCause() != null
                    ? e.getCause() : e;
            if (cause instanceof BadRequest) {
                code = 400;
                body = Map.of("error", cause.getMessage());
            } else {
                code = 500;
                body = Map.of("error", String.valueOf(cause));
            }
        }
        byte[] out = gson.toJson(body).getBytes(StandardCharsets.UTF_8);
        ex.getResponseHeaders().set("Content-Type", "application/json");
        ex.sendResponseHeaders(code, out.length);
        try (OutputStream os = ex.getResponseBody()) {
            os.write(out);
        }
    }

    private static JsonObject readBody(HttpExchange ex) throws IOException, BadRequest {
        try (InputStream in = ex.getRequestBody()) {
            byte[] raw = in.readNBytes(1 << 16);
            try {
                return JsonParser.parseString(new String(raw, StandardCharsets.UTF_8))
                        .getAsJsonObject();
            } catch (RuntimeException e) {
                throw new BadRequest("the body is a JSON object");
            }
        }
    }

    static final class BadRequest extends Exception {
        BadRequest(String why) {
            super(why);
        }
    }

    <T> T onMain(java.util.concurrent.Callable<T> work) throws Exception {
        if (Bukkit.isPrimaryThread()) {
            return work.call();
        }
        Future<T> f = Bukkit.getScheduler().callSyncMethod(this, work);
        return f.get(SYNC_TIMEOUT_S, TimeUnit.SECONDS);
    }

    private Map<String, Object> health() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("version", getDescription().getVersion());
        out.put("server", Bukkit.getVersion());
        return out;
    }

    // -- what players just did ------------------------------------------------

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onPlace(BlockPlaceEvent e) {
        remember(e.getPlayer(), "placed", e.getBlockPlaced());
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onBreak(BlockBreakEvent e) {
        remember(e.getPlayer(), "broke", e.getBlock());
    }

    @EventHandler
    public void onQuit(PlayerQuitEvent e) {
        recent.remove(e.getPlayer().getUniqueId());
    }

    private void remember(Player p, String action, Block b) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("t", System.currentTimeMillis() / 1000);
        row.put("action", action);
        row.put("block", b.getBlockData().getAsString());
        row.put("x", b.getX());
        row.put("y", b.getY());
        row.put("z", b.getZ());
        Deque<Map<String, Object>> q = recent.computeIfAbsent(p.getUniqueId(), k -> new ArrayDeque<>());
        synchronized (q) {
            q.addFirst(row);
            while (q.size() > RECENT_MAX) {
                q.removeLast();
            }
        }
    }

    // -- the state of the world ---------------------------------------------------

    private Map<String, Object> state() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("t", System.currentTimeMillis() / 1000);
        List<Map<String, Object>> worlds = new ArrayList<>();
        for (World w : Bukkit.getWorlds()) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("dimension", dimension(w));
            row.put("time", w.getTime());
            row.put("day", w.getFullTime() / 24000);
            row.put("storm", w.hasStorm());
            row.put("thunder", w.isThundering());
            worlds.add(row);
        }
        out.put("worlds", worlds);
        List<Map<String, Object>> players = new ArrayList<>();
        for (Player p : Bukkit.getOnlinePlayers()) {
            try {
                players.add(player(p));
            } catch (RuntimeException e) {
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", p.getName());
                row.put("error", String.valueOf(e));
                players.add(row);
            }
        }
        out.put("players", players);
        return out;
    }

    static String dimension(World w) {
        try {
            return w.getKey().toString();
        } catch (Throwable t) {
            switch (w.getEnvironment()) {
                case NETHER:
                    return "minecraft:the_nether";
                case THE_END:
                    return "minecraft:the_end";
                default:
                    return "minecraft:overworld";
            }
        }
    }

    private static double r2(double v) {
        return Math.round(v * 100.0) / 100.0;
    }

    private Map<String, Object> player(Player p) {
        Map<String, Object> row = new LinkedHashMap<>();
        Location loc = p.getLocation();
        World w = p.getWorld();
        row.put("name", p.getName());
        row.put("uuid", p.getUniqueId().toString());
        row.put("dimension", dimension(w));
        row.put("pos", List.of(r2(loc.getX()), r2(loc.getY()), r2(loc.getZ())));
        row.put("yaw", r2(loc.getYaw()));
        row.put("pitch", r2(loc.getPitch()));
        row.put("health", r2(p.getHealth()));
        row.put("food", p.getFoodLevel());
        row.put("level", p.getLevel());
        row.put("gamemode", p.getGameMode().name().toLowerCase(Locale.ROOT));
        List<String> doing = new ArrayList<>();
        if (p.isSneaking()) doing.add("sneaking");
        if (p.isSprinting()) doing.add("sprinting");
        if (p.isFlying()) doing.add("flying");
        if (p.isGliding()) doing.add("gliding");
        if (p.isSwimming()) doing.add("swimming");
        if (p.isSleeping()) doing.add("sleeping");
        if (p.isInsideVehicle() && p.getVehicle() != null) {
            doing.add("riding " + key(p.getVehicle().getType().getKey().toString()));
        }
        row.put("doing", doing);
        Block feet = loc.getBlock();
        row.put("standing_on", feet.getRelative(0, -1, 0).getBlockData().getAsString());
        row.put("light", feet.getLightLevel());
        try {
            row.put("biome", feet.getBiome().getKey().toString());
        } catch (Throwable ignored) {
            // A server whose biome API moved: the rest still answers.
        }
        Location eye = p.getEyeLocation();
        Vector dir = eye.getDirection();
        RayTraceResult hit = w.rayTraceBlocks(eye, dir, REACH, FluidCollisionMode.NEVER, false);
        if (hit != null && hit.getHitBlock() != null) {
            Block b = hit.getHitBlock();
            Map<String, Object> at = new LinkedHashMap<>();
            at.put("x", b.getX());
            at.put("y", b.getY());
            at.put("z", b.getZ());
            at.put("block", b.getBlockData().getAsString());
            if (hit.getHitBlockFace() != null) {
                at.put("face", hit.getHitBlockFace().name().toLowerCase(Locale.ROOT));
            }
            at.put("distance", r2(hit.getHitPosition().distance(eye.toVector())));
            row.put("looking_at", at);
        }
        RayTraceResult seen = w.rayTraceEntities(eye, dir, ENTITY_REACH, 0.3, e -> !e.equals(p));
        if (seen != null && seen.getHitEntity() != null) {
            Map<String, Object> ent = entity(seen.getHitEntity(), loc);
            Double blockDist = hit != null ? hit.getHitPosition().distance(eye.toVector()) : null;
            double entDist = seen.getHitPosition().distance(eye.toVector());
            if (blockDist == null || entDist < blockDist) {
                row.put("looking_at_entity", ent);
            }
        }
        row.put("holding", item(p.getInventory().getItemInMainHand()));
        Map<String, Object> off = item(p.getInventory().getItemInOffHand());
        if (off != null) {
            row.put("offhand", off);
        }
        List<String> armor = new ArrayList<>();
        for (ItemStack s : p.getInventory().getArmorContents()) {
            if (s != null && s.getType() != Material.AIR) {
                armor.add(key(s.getType().getKey().toString()));
            }
        }
        row.put("armor", armor);
        Map<String, Integer> counts = new TreeMap<>();
        for (ItemStack s : p.getInventory().getStorageContents()) {
            if (s != null && s.getType() != Material.AIR) {
                counts.merge(key(s.getType().getKey().toString()), s.getAmount(), Integer::sum);
            }
        }
        List<Map.Entry<String, Integer>> sorted = new ArrayList<>(counts.entrySet());
        sorted.sort(Map.Entry.<String, Integer>comparingByValue().reversed());
        Map<String, Integer> inv = new LinkedHashMap<>();
        for (Map.Entry<String, Integer> e : sorted.subList(0, Math.min(INVENTORY_MAX, sorted.size()))) {
            inv.put(e.getKey(), e.getValue());
        }
        row.put("inventory", inv);
        List<Map<String, Object>> near = new ArrayList<>();
        for (Entity e : p.getNearbyEntities(NEARBY, NEARBY / 2, NEARBY)) {
            if (e instanceof LivingEntity || e instanceof org.bukkit.entity.Item
                    || e instanceof org.bukkit.entity.Vehicle) {
                near.add(entity(e, loc));
            }
        }
        near.sort(Comparator.comparingDouble(m -> ((Number) m.get("distance")).doubleValue()));
        row.put("nearby", near.size() > NEARBY_MAX ? new ArrayList<>(near.subList(0, NEARBY_MAX)) : near);
        Deque<Map<String, Object>> q = recent.get(p.getUniqueId());
        if (q != null) {
            synchronized (q) {
                row.put("recent_blocks", new ArrayList<>(q));
            }
        }
        return row;
    }

    private static String key(String namespaced) {
        return namespaced.startsWith("minecraft:") ? namespaced.substring(10) : namespaced;
    }

    @SuppressWarnings("deprecation")
    private static Map<String, Object> entity(Entity e, Location from) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("type", key(e.getType().getKey().toString()));
        String name = e instanceof Player ? ((Player) e).getName() : e.getCustomName();
        if (name != null) {
            m.put("name", name);
        }
        if (e instanceof org.bukkit.entity.Item) {
            ItemStack s = ((org.bukkit.entity.Item) e).getItemStack();
            m.put("item", key(s.getType().getKey().toString()));
            m.put("count", s.getAmount());
        }
        Location l = e.getLocation();
        m.put("x", (int) Math.floor(l.getX()));
        m.put("y", (int) Math.floor(l.getY()));
        m.put("z", (int) Math.floor(l.getZ()));
        m.put("distance", r2(l.distance(from)));
        return m;
    }

    @SuppressWarnings("deprecation")
    private static Map<String, Object> item(ItemStack s) {
        if (s == null || s.getType() == Material.AIR) {
            return null;
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("item", key(s.getType().getKey().toString()));
        m.put("count", s.getAmount());
        ItemMeta meta = s.getItemMeta();
        if (meta != null && meta.hasDisplayName()) {
            m.put("name", meta.getDisplayName());
        }
        return m;
    }

    // -- blocks in a box ------------------------------------------------------------

    World worldOf(String dim) {
        String want = dim == null || dim.isBlank() ? "minecraft:overworld" : dim.trim().toLowerCase(Locale.ROOT);
        if (!want.contains(":")) {
            want = "minecraft:" + Map.of("nether", "the_nether", "end", "the_end").getOrDefault(want, want);
        }
        for (World w : Bukkit.getWorlds()) {
            if (dimension(w).equals(want)) {
                return w;
            }
        }
        return null;
    }

    private static int num(JsonObject o, String k) throws BadRequest {
        try {
            return o.get(k).getAsInt();
        } catch (RuntimeException e) {
            throw new BadRequest(k + " is a whole number");
        }
    }

    private Object blocks(JsonObject req) throws Exception {
        String dim = req.has("dimension") && !req.get("dimension").isJsonNull()
                ? req.get("dimension").getAsString() : null;
        int x1 = num(req, "x1"), y1 = num(req, "y1"), z1 = num(req, "z1");
        int x2 = num(req, "x2"), y2 = num(req, "y2"), z2 = num(req, "z2");
        final int ax = Math.min(x1, x2), bx = Math.max(x1, x2);
        final int ay = Math.min(y1, y2), by = Math.max(y1, y2);
        final int az = Math.min(z1, z2), bz = Math.max(z1, z2);
        long cells = (long) (bx - ax + 1) * (by - ay + 1) * (bz - az + 1);
        if (cells > BOX_MAX) {
            throw new BadRequest("at most " + BOX_MAX + " blocks in one read");
        }
        // The chunks are copied on the server thread; encoding happens here.
        Object taken = onMain(() -> {
            World w = worldOf(dim);
            if (w == null) {
                return Map.of("unread", Map.of("code", "no_region",
                        "why", "The server has no world for the dimension " + dim + "."));
            }
            Map<Long, ChunkSnapshot> snaps = new HashMap<>();
            int loads = 0;
            for (int cx = ax >> 4; cx <= bx >> 4; cx++) {
                for (int cz = az >> 4; cz <= bz >> 4; cz++) {
                    if (!w.isChunkLoaded(cx, cz)) {
                        if (!w.isChunkGenerated(cx, cz)) {
                            Map<String, Object> u = new LinkedHashMap<>();
                            u.put("code", "not_generated");
                            u.put("chunk", List.of(cx, cz));
                            u.put("why", "Part of that area (chunk " + cx + ", " + cz + " — x "
                                    + (cx * 16) + " to " + (cx * 16 + 15) + ", z " + (cz * 16)
                                    + " to " + (cz * 16 + 15) + ") has never been generated; "
                                    + "somebody has to go there first.");
                            return Map.of("unread", u);
                        }
                        if (++loads > CHUNK_LOADS_MAX) {
                            throw new BadRequest("that box reaches too many unloaded chunks");
                        }
                    }
                    snaps.put(((long) cx << 32) ^ (cz & 0xffffffffL),
                            w.getChunkAt(cx, cz).getChunkSnapshot(false, false, false));
                }
            }
            return new Object[]{w.getMinHeight(), w.getMaxHeight(), snaps, dimension(w)};
        });
        if (taken instanceof Map) {
            return taken;
        }
        Object[] t = (Object[]) taken;
        int minY = (Integer) t[0], maxY = (Integer) t[1];
        @SuppressWarnings("unchecked")
        Map<Long, ChunkSnapshot> snaps = (Map<Long, ChunkSnapshot>) t[2];
        Map<String, Integer> palette = new LinkedHashMap<>();
        palette.put("minecraft:air", 0);
        int[] out = new int[(int) cells];
        int i = 0;
        // Order: x, then z, then y (y changes fastest) — the panel decodes it so.
        for (int x = ax; x <= bx; x++) {
            for (int z = az; z <= bz; z++) {
                ChunkSnapshot s = snaps.get(((long) (x >> 4) << 32) ^ ((z >> 4) & 0xffffffffL));
                for (int y = ay; y <= by; y++) {
                    if (y < minY || y >= maxY) {
                        out[i++] = 0;
                        continue;
                    }
                    String st = s.getBlockData(x & 15, y, z & 15).getAsString();
                    Integer idx = palette.get(st);
                    if (idx == null) {
                        idx = palette.size();
                        palette.put(st, idx);
                    }
                    out[i++] = idx;
                }
            }
        }
        Map<String, Object> res = new LinkedHashMap<>();
        res.put("dimension", t[3]);
        res.put("box", List.of(ax, ay, az, bx, by, bz));
        res.put("palette", new ArrayList<>(palette.keySet()));
        res.put("cells", out);
        return res;
    }
}
