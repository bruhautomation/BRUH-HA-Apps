#!/usr/bin/env python3
"""
convert-java-pack-to-bedrock.py — best-effort Java -> Bedrock resource pack
converter so iPad/iPhone (Bedrock) clients get a curated world's custom
textures pushed by Geyser on join, with ZERO local installs.

Why this exists
---------------
Bedrock Edition cannot load Java resource packs (different format) and cannot
load Java/Fabric mods at all. But Geyser will auto-send any *Bedrock* pack
placed in `plugins/Geyser-Spigot/packs/` to Bedrock clients when they connect.
So if we convert a curated world's Java pack into a valid Bedrock pack, the
iPads get the textures with no manual step. This is the "all server-side"
requirement for family Bedrock play.

What converts (best-effort)
---------------------------
* Block textures   -> textures/blocks/ + textures/terrain_texture.json
* Item textures    -> textures/items/ + textures/item_texture.json
* pack icon        -> pack_icon.png
* a valid manifest.json (deterministic UUIDs derived from the pack name)

What does NOT convert (Bedrock platform limits — documented, not a bug):
* Custom 3D block/item models (Java CustomModelData) — no Bedrock equivalent.
* Animated texture timing (.mcmeta) — animated source textures are skipped so
  they don't render as stretched still images.
* Sounds, fonts, language files, shaders.

The result is always a *valid* pack Geyser can push, even if a given Java pack
only converts partially. Texture-name differences across editions are handled
by scripts/java2bedrock-map.json with an identity fallback (many block/item
names already match across editions).

Usage:
    convert-java-pack-to-bedrock.py <java_pack.zip> <out.mcpack> <name> [map.json]

Exit codes: 0 success, 2 bad input, 1 conversion failure.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

# Stable namespace so the same pack name always yields the same UUIDs — Bedrock
# clients cache packs by UUID+version, so re-converting must not churn them.
_NS = uuid.UUID("6f0b5d6e-9b1a-5c3a-9f2e-b00bfacecafe")

DEFAULT_MAP = Path(__file__).resolve().parent / "java2bedrock-map.json"


def _det_uuid(name: str, suffix: str) -> str:
    return str(uuid.uuid5(_NS, f"{name}:{suffix}"))


def _load_map(map_path: Path | None) -> dict:
    path = map_path or DEFAULT_MAP
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {"blocks": {}, "items": {}}
    return {
        "blocks": dict(data.get("blocks", {})),
        "items": dict(data.get("items", {})),
    }


def _find_assets_textures(root: Path) -> Path | None:
    """Locate <root>/.../assets/minecraft/textures, tolerating a wrapper dir
    (some packs zip a folder containing pack.mcmeta rather than its contents)."""
    for mcmeta in [root / "pack.mcmeta", *root.glob("*/pack.mcmeta")]:
        base = mcmeta.parent
        tex = base / "assets" / "minecraft" / "textures"
        if tex.is_dir():
            return tex
    # Fall back: any assets/minecraft/textures anywhere in the tree.
    for tex in root.rglob("assets/minecraft/textures"):
        if tex.is_dir():
            return tex
    return None


def _pack_description(root: Path) -> str:
    for mcmeta in [root / "pack.mcmeta", *root.glob("*/pack.mcmeta")]:
        try:
            data = json.loads(mcmeta.read_text())
            desc = data.get("pack", {}).get("description")
            if isinstance(desc, str):
                return desc[:120]
        except (OSError, ValueError):
            # This mcmeta is unreadable or not JSON; the next candidate gets a turn.
            pass
    return ""


def _copy_texture_set(src_dirs: list[Path], out_dir: Path, name_map: dict) -> dict:
    """Copy *.png from the first existing src dir into out_dir, applying the
    Java->Bedrock name map (identity fallback). Skips animated textures (those
    with a sibling .png.mcmeta) so they don't render as stretched stills.
    Returns the texture_data dict for the Bedrock atlas json."""
    texture_data: dict[str, dict] = {}
    src = next((d for d in src_dirs if d.is_dir()), None)
    if src is None:
        return texture_data
    out_dir.mkdir(parents=True, exist_ok=True)
    rel_prefix = "/".join(out_dir.parts[out_dir.parts.index("textures"):])
    for png in sorted(src.glob("*.png")):
        if (src / f"{png.name}.mcmeta").exists():
            continue  # animated — skip (best-effort)
        basename = png.stem
        bedrock_key = name_map.get(basename, basename)
        dest = out_dir / f"{bedrock_key}.png"
        try:
            shutil.copyfile(png, dest)
        except OSError:
            continue
        texture_data[bedrock_key] = {"textures": f"{rel_prefix}/{bedrock_key}"}
    return texture_data


def convert(java_zip: Path, out_mcpack: Path, name: str,
            map_path: Path | None = None) -> dict:
    """Convert a Java pack zip into a Bedrock .mcpack. Returns a summary dict
    with counts. Raises ValueError on unusable input."""
    java_zip = Path(java_zip)
    out_mcpack = Path(out_mcpack)
    if not java_zip.is_file():
        raise ValueError(f"java pack not found: {java_zip}")
    name_map = _load_map(map_path)

    with tempfile.TemporaryDirectory(prefix="j2b-src-") as src_tmp, \
         tempfile.TemporaryDirectory(prefix="j2b-out-") as out_tmp:
        src_root = Path(src_tmp)
        out_root = Path(out_tmp)
        try:
            with zipfile.ZipFile(java_zip) as zf:
                # zip-slip guard
                for member in zf.namelist():
                    resolved = (src_root / member).resolve()
                    if src_root.resolve() not in resolved.parents \
                       and resolved != src_root.resolve():
                        raise ValueError(f"unsafe path in zip: {member}")
                zf.extractall(src_root)
        except zipfile.BadZipFile as exc:
            raise ValueError(f"not a valid zip: {exc}") from exc

        textures = _find_assets_textures(src_root)
        if textures is None:
            raise ValueError("no assets/minecraft/textures found — not a Java pack")

        # --- manifest.json -------------------------------------------------
        desc = _pack_description(src_root) or f"{name} (auto-converted for Bedrock)"
        manifest = {
            "format_version": 2,
            "header": {
                "name": name,
                "description": desc,
                "uuid": _det_uuid(name, "header"),
                "version": [1, 0, 0],
                "min_engine_version": [1, 20, 0],
            },
            "modules": [{
                "type": "resources",
                "uuid": _det_uuid(name, "module"),
                "version": [1, 0, 0],
            }],
        }
        (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # --- pack icon -----------------------------------------------------
        for icon_src in [textures.parent.parent.parent / "pack.png",
                         *src_root.rglob("pack.png")]:
            if icon_src.is_file():
                shutil.copyfile(icon_src, out_root / "pack_icon.png")
                break

        # --- block + item textures ----------------------------------------
        tex_out = out_root / "textures"
        terrain = _copy_texture_set(
            [textures / "block", textures / "blocks"],
            tex_out / "blocks", name_map["blocks"],
        )
        items = _copy_texture_set(
            [textures / "item", textures / "items"],
            tex_out / "items", name_map["items"],
        )

        if terrain:
            (tex_out / "terrain_texture.json").write_text(json.dumps({
                "resource_pack_name": name,
                "texture_name": "atlas.terrain",
                "padding": 8,
                "num_mip_levels": 4,
                "texture_data": terrain,
            }, indent=2))
        if items:
            (tex_out / "item_texture.json").write_text(json.dumps({
                "resource_pack_name": name,
                "texture_name": "atlas.items",
                "texture_data": items,
            }, indent=2))

        # --- zip into .mcpack ---------------------------------------------
        out_mcpack.parent.mkdir(parents=True, exist_ok=True)
        tmp_zip = out_mcpack.with_suffix(out_mcpack.suffix + ".tmp")
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for entry in sorted(out_root.rglob("*")):
                if entry.is_file():
                    zf.write(entry, entry.relative_to(out_root))
        os.replace(tmp_zip, out_mcpack)

    return {
        "ok": True,
        "name": name,
        "blocks": len(terrain),
        "items": len(items),
        "output": str(out_mcpack),
        "size": out_mcpack.stat().st_size,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print("usage: convert-java-pack-to-bedrock.py <java_pack.zip> "
              "<out.mcpack> <name> [map.json]", file=sys.stderr)
        return 2
    java_zip, out_mcpack, name = argv[1], argv[2], argv[3]
    map_path = Path(argv[4]) if len(argv) > 4 else None
    try:
        result = convert(Path(java_zip), Path(out_mcpack), name, map_path)
    except ValueError as exc:
        print(f"[j2b] conversion failed: {exc}", file=sys.stderr)
        return 1
    print(f"[j2b] converted '{name}': {result['blocks']} block + "
          f"{result['items']} item textures -> {result['output']} "
          f"({result['size']} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
