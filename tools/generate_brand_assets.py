"""Brand asset generator for Otis AI Companion.

Produces all 8 Home Assistant brand assets conforming to official dimensions:
- icon.png (256x256), icon@2x.png (512x512)
- dark_icon.png (256x256), dark_icon@2x.png (512x512)
- logo.png (1169x256), logo@2x.png (2048x448)
- dark_logo.png (1169x256), dark_logo@2x.png (2048x448)
"""

import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SRC_IMAGE_PATH = "/home/jamie/.gemini/antigravity-ide/brain/a9b39052-efd7-4720-a37b-3c433176c2fe/otis_ai_architect_1793115462050.jpg"
FONT_PATH = "/usr/share/fonts/truetype/inter-zorin-os/Inter-Regular.ttf"


def extract_emblems():
    img = Image.open(SRC_IMAGE_PATH).convert("RGB")
    arr = np.array(img, dtype=np.float32)

    # Isolate house emblem without text (Y: 160 to 695, X: 195 to 830)
    emblem_arr = arr[160:695, 195:830]

    diff = 255.0 - emblem_arr
    max_diff = np.max(diff, axis=2)
    alpha = np.clip((max_diff - 4.0) / (255.0 - 4.0), 0.0, 1.0)
    alpha = np.power(alpha, 0.95)

    fg = np.zeros_like(emblem_arr)
    for c in range(3):
        fg[:, :, c] = np.clip(
            (emblem_arr[:, :, c] - (1.0 - alpha) * 255.0) / np.maximum(alpha, 0.01),
            0.0,
            255.0,
        )

    light_rgba = np.dstack([fg, alpha * 255.0]).astype(np.uint8)
    light_emblem = Image.fromarray(light_rgba, "RGBA")

    # Dark mode adaptation
    rgb = fg.copy()
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    lum = 0.299 * r + 0.587 * g + 0.114 * b

    h, w = rgb.shape[:2]
    y_norm = np.linspace(0, 1, h)[:, None, None]

    top_col = np.array([56.0, 189.0, 248.0]).reshape(1, 1, 3)  # #38BDF8 Sky Cyan
    bot_col = np.array([192.0, 132.0, 252.0]).reshape(1, 1, 3)  # #C084FC Bright Lavender Purple

    grad = (1.0 - y_norm) * top_col + y_norm * bot_col
    grad = np.repeat(grad, w, axis=1)

    cyan_core = (b > 180) & (g > 150) & (r < 180) & (alpha > 0.15)
    dark_lines = (lum < 115) & (alpha > 0.15)
    mid_tones = (lum >= 115) & (lum < 200) & (~cyan_core) & (alpha > 0.15)

    dark_rgb = rgb.copy()
    dark_rgb[dark_lines] = grad[dark_lines] * 1.1
    dark_rgb[mid_tones] = 0.25 * dark_rgb[mid_tones] + 0.75 * grad[mid_tones]

    dark_rgb[cyan_core, 0] = np.clip(rgb[cyan_core, 0] * 1.2 + 20, 0, 255)
    dark_rgb[cyan_core, 1] = np.clip(rgb[cyan_core, 1] * 1.15 + 20, 0, 255)
    dark_rgb[cyan_core, 2] = 255.0
    dark_rgb = np.clip(dark_rgb, 0, 255)

    dark_rgba = np.dstack([dark_rgb, alpha * 255.0]).astype(np.uint8)
    dark_emblem = Image.fromarray(dark_rgba, "RGBA")

    return light_emblem, dark_emblem


def make_icon(emblem, size):
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ew, eh = emblem.size

    max_dim = int(size * 0.86)
    scale = min(max_dim / ew, max_dim / eh)
    nw = int(ew * scale)
    nh = int(eh * scale)

    resized = emblem.resize((nw, nh), Image.Resampling.LANCZOS)
    x = (size - nw) // 2
    y = (size - nh) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas


def make_logo(emblem, target_w, target_h, is_dark=False):
    canvas = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    scale = target_h / 256.0
    ew, eh = emblem.size
    target_emb_h = int(210 * scale)
    target_emb_w = int(ew * (target_emb_h / eh))

    emb_resized = emblem.resize((target_emb_w, target_emb_h), Image.Resampling.LANCZOS)
    emb_x = int(48 * scale)
    emb_y = int((target_h - target_emb_h) / 2)
    canvas.paste(emb_resized, (emb_x, emb_y), emb_resized)

    text = "Otis AI Companion"
    font_size = int(78 * scale)
    font = ImageFont.truetype(FONT_PATH, font_size)

    text_color = (241, 245, 249, 255) if is_dark else (45, 55, 72, 255)

    text_x = emb_x + target_emb_w + int(45 * scale)
    bbox = font.getbbox(text)
    text_h = bbox[3] - bbox[1]
    text_y = int((target_h - text_h) / 2) - int(6 * scale)

    draw.text((text_x, text_y), text, fill=text_color, font=font)
    return canvas


def main():
    light_emblem, dark_emblem = extract_emblems()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    brand_dir = os.path.join(base_dir, "custom_components", "otis_ai", "brand")
    os.makedirs(brand_dir, exist_ok=True)

    targets = [
        ("icon.png", make_icon(light_emblem, 256)),
        ("icon@2x.png", make_icon(light_emblem, 512)),
        ("dark_icon.png", make_icon(dark_emblem, 256)),
        ("dark_icon@2x.png", make_icon(dark_emblem, 512)),
        ("logo.png", make_logo(light_emblem, 1169, 256, is_dark=False)),
        ("logo@2x.png", make_logo(light_emblem, 2048, 448, is_dark=False)),
        ("dark_logo.png", make_logo(dark_emblem, 1169, 256, is_dark=True)),
        ("dark_logo@2x.png", make_logo(dark_emblem, 2048, 448, is_dark=True)),
    ]

    for filename, img_obj in targets:
        out_file = os.path.join(brand_dir, filename)
        img_obj.save(out_file, optimize=True)
        print(f"Saved {filename}: {img_obj.size[0]}x{img_obj.size[1]} ({os.path.getsize(out_file)} bytes)")


if __name__ == "__main__":
    main()
