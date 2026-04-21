"""
Satellite Imagery Resolution Demo - Tile Generator v2
Downloads large areas of real satellite imagery and creates multi-resolution
tile pyramids for the interactive web viewer.

Sources:
  - SAR:     Umbra Open Data - Port of Long Beach, CA (35cm GEC, X-band)
  - Optical: Maxar Open Data - LA Wildfires (30cm visual, WorldView-2)

Extracts the full available extent (up to 8192x8192) to allow exploring
a large area of the scene.
"""

import os
import json
import math
import sys
import numpy as np
import cv2
import rasterio
from rasterio.windows import Window

# ---- Configuration ----
TILE_SIZE = 256

# How big a chip to extract (full scenes can be 17k-32k px; we take a big useful chunk)
MAX_CHIP = 8192

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tiles")

# Maxar Optical — LA Wildfires, WV02, ~30cm visual RGB
MAXAR_VISUAL_COG = (
    "https://maxar-opendata.s3.amazonaws.com/events/WildFires-LosAngeles-Jan-2025/"
    "ard/11/031311102030/2024-12-14/103001010A705C00-visual.tif"
)
MAXAR_RES = 0.30  # m/px

# Umbra SAR — Port of Long Beach, UMBRA-05, 35cm GEC
UMBRA_GEC_COG = (
    "https://umbra-open-data-catalog.s3.amazonaws.com/sar-data/tasks/"
    "Port%20of%20Long%20Beach,%20California,%20United%20States/"
    "073fb113-9502-49f1-b37a-571fe53eca0e/"
    "2025-06-22-04-38-11_UMBRA-05/2025-06-22-04-38-11_UMBRA-05_GEC.tif"
)
UMBRA_RES = 0.35  # m/px (GEC product resolution)


def extract_chip_from_cog(cog_url, max_size, is_sar=False, offset_x=0, offset_y=0):
    """
    Read a large chip from a Cloud-Optimized GeoTIFF via HTTP range requests.
    Center-crops to max_size x max_size, with optional pixel offsets from center.
    """
    print(f"  Opening COG: ...{cog_url[-60:]}")

    env = rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
        AWS_NO_SIGN_REQUEST='YES',
        GDAL_HTTP_MAX_RETRY=5,
        GDAL_HTTP_RETRY_DELAY=3,
        CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif,.tiff'
    )

    with env:
        with rasterio.open(cog_url) as src:
            w, h = src.width, src.height
            print(f"  Full image: {w}x{h}, bands: {src.count}, dtype: {src.dtypes[0]}")

            chip_w = min(max_size, w)
            chip_h = min(max_size, h)
            col_off = max(0, min((w - chip_w) // 2 + offset_x, w - chip_w))
            row_off = max(0, min((h - chip_h) // 2 + offset_y, h - chip_h))

            window = Window(col_off, row_off, chip_w, chip_h)
            print(f"  Reading window: {chip_w}x{chip_h} from offset ({col_off}, {row_off})...")

            if is_sar:
                # SAR GEC is typically uint8 or uint16 amplitude
                data = src.read(1, window=window)
                dtype_orig = data.dtype
                print(f"  SAR dtype: {dtype_orig}, min={data.min()}, max={data.max()}")
                
                if dtype_orig == np.uint8:
                    # Already 8-bit — just use directly with a contrast stretch
                    chip = data.copy()
                    # Simple percentile contrast stretch for better visibility
                    valid = chip > 0
                    if np.any(valid):
                        p1, p99 = np.percentile(chip[valid], (1, 99))
                        chip = np.clip((chip.astype(np.float32) - p1) / (p99 - p1 + 1e-6) * 255, 0, 255).astype(np.uint8)
                else:
                    # Float or 16-bit: apply log-scale
                    data = data.astype(np.float64)
                    valid = data > 0
                    if np.any(valid):
                        data[valid] = 20.0 * np.log10(data[valid] + 1)
                        p2, p98 = np.percentile(data[valid], (2, 98))
                        data = np.clip((data - p2) / (p98 - p2 + 1e-8) * 255, 0, 255)
                    chip = data.astype(np.uint8)

                chip = np.stack([chip, chip, chip], axis=-1)  # grayscale -> RGB
            else:
                # Optical RGB
                bands = min(3, src.count)
                data = src.read(list(range(1, bands + 1)), window=window)
                
                if data.dtype != np.uint8:
                    out = np.zeros_like(data, dtype=np.uint8)
                    for b in range(data.shape[0]):
                        band = data[b].astype(np.float64)
                        valid = band > 0
                        if np.any(valid):
                            p2, p98 = np.percentile(band[valid], (2, 98))
                            out[b] = np.clip((band - p2) / (p98 - p2 + 1e-8) * 255, 0, 255).astype(np.uint8)
                    data = out
                
                chip = np.transpose(data, (1, 2, 0))  # CHW -> HWC
                if chip.shape[2] == 1:
                    chip = np.repeat(chip, 3, axis=2)

            print(f"  Chip shape: {chip.shape}")
            return chip


def create_tile_pyramid(folder_name, base_img, resolution_m, source_info):
    """
    Create tiles at multiple resolution levels.
    """
    print(f"\nTiling '{folder_name}' (native {resolution_m}m, {base_img.shape[1]}x{base_img.shape[0]})...")
    base_dir = os.path.join(OUTPUT_DIR, folder_name)
    os.makedirs(base_dir, exist_ok=True)

    h, w = base_img.shape[:2]

    scales = {
        "0.03125x": 0.03125,
        "0.0625x":  0.0625,
        "0.125x":   0.125,
        "0.25x":    0.25,
        "0.5x":     0.5,
        "1x":       1.0,
    }

    metadata = {
        "name": folder_name,
        "source": source_info,
        "native_resolution_m": resolution_m,
        "base_width": w,
        "base_height": h,
        "tile_size": TILE_SIZE,
        "scales": {}
    }

    for scale_key, scale_factor in scales.items():
        print(f"  {scale_key}...", end=" ", flush=True)
        scale_dir = os.path.join(base_dir, scale_key)
        os.makedirs(scale_dir, exist_ok=True)

        if scale_factor < 1.0:
            # Downscale with area averaging, then nearest-neighbor back up
            sw = max(1, int(w * scale_factor))
            sh = max(1, int(h * scale_factor))
            small = cv2.resize(base_img, (sw, sh), interpolation=cv2.INTER_AREA)
            layer_img = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        else:
            layer_img = base_img

        effective_res = resolution_m / scale_factor
        cols = math.ceil(w / TILE_SIZE)
        rows = math.ceil(h / TILE_SIZE)

        for x in range(cols):
            x_dir = os.path.join(scale_dir, str(x))
            os.makedirs(x_dir, exist_ok=True)
            for y in range(rows):
                sy, sx = y * TILE_SIZE, x * TILE_SIZE
                tile = layer_img[sy:sy+TILE_SIZE, sx:sx+TILE_SIZE]
                th, tw = tile.shape[:2]
                if th < TILE_SIZE or tw < TILE_SIZE:
                    padded = np.zeros((TILE_SIZE, TILE_SIZE, 3), dtype=np.uint8)
                    padded[:th, :tw] = tile
                    tile = padded
                cv2.imwrite(
                    os.path.join(x_dir, f"{y}.jpg"),
                    cv2.cvtColor(tile, cv2.COLOR_RGB2BGR),
                    [cv2.IMWRITE_JPEG_QUALITY, 85]
                )

        metadata["scales"][scale_key] = {
            "factor": scale_factor,
            "effective_resolution_m": round(effective_res, 4),
            "cols": cols,
            "rows": rows,
        }
        print(f"{cols}x{rows} tiles, eff. {effective_res:.3f}m")

    meta_path = os.path.join(base_dir, "metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)
    return metadata


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ===== OPTICAL =====
    print("=" * 60)
    print("OPTICAL: Maxar WV02 30cm — LA Wildfires")
    print("=" * 60)
    optical_chip = extract_chip_from_cog(MAXAR_VISUAL_COG, MAX_CHIP, is_sar=False)
    optical_meta = create_tile_pyramid("optical", optical_chip, MAXAR_RES, {
        "provider": "Maxar (WorldView-2)",
        "location": "Los Angeles, CA",
        "event": "LA Wildfires Jan 2025",
        "resolution": "30cm GSD",
        "license": "CC-BY-NC-4.0",
        "bands": "RGB Visual"
    })

    # ===== SAR =====
    print("\n" + "=" * 60)
    print("SAR: Umbra UMBRA-05 35cm — Port of Long Beach, CA")
    print("=" * 60)
    sar_chip = extract_chip_from_cog(UMBRA_GEC_COG, MAX_CHIP, is_sar=True,
                                      offset_x=4000, offset_y=-3000)
    sar_meta = create_tile_pyramid("sar", sar_chip, UMBRA_RES, {
        "provider": "Umbra (UMBRA-05)",
        "location": "Port of Long Beach, CA",
        "date": "2025-06-22",
        "resolution": "35cm GEC",
        "license": "CC-BY-4.0",
        "band": "X-band SAR (VV)"
    })

    # ===== CONFIG =====
    config = {"optical": optical_meta, "sar": sar_meta, "tile_size": TILE_SIZE}
    config_path = os.path.join(OUTPUT_DIR, "config.json")
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nDONE — tiles at {OUTPUT_DIR}")
    print(f"Config: {config_path}")


if __name__ == "__main__":
    main()
