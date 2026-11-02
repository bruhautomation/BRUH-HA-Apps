# A spyglass was used this tick: number the use, tag the player, start the hold.
scoreboard players add @a[scores={bruh_spy=1..}] bruh_spy_n 1
scoreboard players set @a[scores={bruh_spy=1..}] bruh_spy_t 60
tag @a[scores={bruh_spy=1..}] add bruh_pointing
scoreboard players reset @a[scores={bruh_spy=1..}] bruh_spy
# The tag goes by itself after three seconds: the panel reads the use's
# number and never has to remove it (an RCON `tag` is shown to operators).
scoreboard players remove @a[scores={bruh_spy_t=1..}] bruh_spy_t 1
tag @a[tag=bruh_pointing,scores={bruh_spy_t=..0}] remove bruh_pointing
