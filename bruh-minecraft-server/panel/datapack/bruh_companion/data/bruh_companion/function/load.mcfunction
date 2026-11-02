# BRUH Minecraft's spyglass: a use of any spyglass is counted (bruh_spy),
# numbered per player (bruh_spy_n), and held as the tag bruh_pointing for
# a moment (bruh_spy_t ticks), which the panel polls over RCON.
scoreboard objectives add bruh_spy minecraft.used:minecraft.spyglass
scoreboard objectives add bruh_spy_n dummy
scoreboard objectives add bruh_spy_t dummy
