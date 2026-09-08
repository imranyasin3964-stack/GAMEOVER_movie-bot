import os
import io
import re
import ssl
import uuid
import hashlib
import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import Config

DOWNLOADS_DIR = Config.DOWNLOADS_DIR
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

FONT_PATH = "Roboto-Bold.ttf"
FONT_URLS = [
    "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf",
    "https://raw.githubusercontent.com/googlefonts/roboto/main/src/hinted/Roboto-Bold.ttf",
]

async def download_font():
    """Ensures a modern bold TTF font is present for typography."""
    if os.path.exists(FONT_PATH):
        return
    headers = {"User-Agent": "Mozilla/5.0"}
    connector = aiohttp.TCPConnector(ssl=False)
    for url in FONT_URLS:
        try:
            async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 10000:
                            with open(FONT_PATH, "wb") as f:
                                f.write(data)
                            return
        except Exception:
            pass


def get_system_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Attempts to load Roboto-Bold or system fonts with safe default fallback."""
    candidate_paths = [
        FONT_PATH,
        os.path.join(os.path.dirname(__file__), "..", FONT_PATH),
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "arial.ttf",
        "Arial.ttf",
    ]
    for p in candidate_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    try:
        return ImageFont.load_default()
    except Exception:
        return None


def create_default_movie_poster(w: int = 1280, h: int = 720) -> Image.Image:
    """Creates a sleek, luxurious cinema graphic when no movie poster is available."""
    canvas = Image.new("RGBA", (w, h), (10, 14, 23, 255))
    
    # Ambient radial blue glow in center
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse(
        [(w // 2 - 350, h // 2 - 250), (w // 2 + 350, h // 2 + 250)],
        fill=(30, 58, 138, 95),
    )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=80))
    canvas = Image.alpha_composite(canvas, glow)
    
    # Center clapperboard frame
    card_w, card_h = 380, 540
    card_x = (w - card_w) // 2
    card_y = 48
    
    card_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(card_layer)
    cdraw.rounded_rectangle(
        [(card_x, card_y), (card_x + card_w, card_y + card_h)],
        radius=24,
        fill=(18, 24, 38, 230),
        outline=(56, 189, 248, 140),
        width=2,
    )
    
    # Clapperboard stripes
    stripe_y = card_y + 35
    for i in range(5):
        sx = card_x + 40 + i * 60
        cdraw.polygon(
            [(sx, stripe_y), (sx + 30, stripe_y), (sx + 15, stripe_y + 40), (sx - 15, stripe_y + 40)],
            fill=(56, 189, 248, 80),
        )
        
    font_bold = get_system_font(30)
    font_sub = get_system_font(20)
    
    t1 = "GAMEOVER"
    t2 = "CINEMA"
    if font_bold:
        b1 = cdraw.textbbox((0, 0), t1, font=font_bold)
        cdraw.text((card_x + (card_w - (b1[2] - b1[0])) // 2, card_y + 240), t1, font=font_bold, fill=(255, 255, 255, 240))
    if font_sub:
        b2 = cdraw.textbbox((0, 0), t2, font=font_sub)
        cdraw.text((card_x + (card_w - (b2[2] - b2[0])) // 2, card_y + 285), t2, font=font_sub, fill=(56, 189, 248, 240))
        
    canvas = Image.alpha_composite(canvas, card_layer)
    return canvas.convert("RGB")


async def download_image_bytes(image_url: str) -> bytes | None:
    """
    Robustly downloads poster image bytes:
    1. Direct local file check
    2. Direct CDN download with browser headers & SSL bypass
    3. Global weserv proxy fallback if CDN throttles or blocks
    """
    if not image_url:
        return None

    # Handle local file paths
    if os.path.exists(image_url):
        try:
            with open(image_url, "rb") as f:
                return f.read()
        except Exception:
            pass

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    
    urls_to_try = [
        image_url,
        f"https://images.weserv.nl/?url={image_url}",
    ]

    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        for u in urls_to_try:
            try:
                async with session.get(u, timeout=aiohttp.ClientTimeout(total=6)) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        if len(data) > 2000:
                            return data
            except Exception:
                pass

    return None


def generate_movie_thumbnail_sync(image_data: bytes | None, title: str = "") -> str:
    """
    Synchronous image processor:
    - 16:9 Canvas (1280x720)
    - Movie poster blurred backdrop + dark contrast overlay
    - Large fitted center poster with rounded corners and 3D ambient shadow
    - Sleek bottom branding badge: G A M E O V E R   M O V I E   H U B
    - No duplicate title/duration/fake buttons
    """
    base_w, base_h = 1280, 720

    # 1. Load poster or fallback
    poster = None
    if image_data:
        try:
            poster = Image.open(io.BytesIO(image_data)).convert("RGBA")
        except Exception as e:
            print(f"[Thumbnail] Failed to decode image bytes: {e}")

    if poster is None:
        canvas = create_default_movie_poster(base_w, base_h)
        poster = canvas.convert("RGBA")

    # 2. Background: Crop to 16:9, blur, and dark overlay
    bg = poster.convert("RGB")
    bg_ratio = bg.width / bg.height
    target_ratio = base_w / base_h
    if bg_ratio > target_ratio:
        new_w = int(bg.height * target_ratio)
        left = (bg.width - new_w) // 2
        bg = bg.crop((left, 0, left + new_w, bg.height))
    else:
        new_h = int(bg.width / target_ratio)
        top = (bg.height - new_h) // 2
        bg = bg.crop((0, top, bg.width, top + new_h))

    bg = bg.resize((base_w, base_h), Image.Resampling.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=30))

    # Dark moody overlay
    overlay = Image.new("RGBA", (base_w, base_h), (10, 14, 22, 170))
    bg = Image.alpha_composite(bg.convert("RGBA"), overlay)

    # 3. Fit Center Poster (prominent, full-height fitted)
    max_h = 560
    max_w = 960
    scale = min(max_w / poster.width, max_h / poster.height)
    fit_w = max(10, int(poster.width * scale))
    fit_h = max(10, int(poster.height * scale))

    fit_poster = poster.resize((fit_w, fit_h), Image.Resampling.LANCZOS)

    # Rounded corners mask
    radius = min(24, fit_w // 4, fit_h // 4)
    mask = Image.new("L", (fit_w, fit_h), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([(0, 0), (fit_w, fit_h)], radius=radius, fill=255)
    fit_poster.putalpha(mask)

    # Calculate center position
    pos_x = (base_w - fit_w) // 2
    pos_y = 45 + (max_h - fit_h) // 2

    # 4. Soft 3D Drop Shadow behind poster
    shadow_pad = 40
    shadow_w = fit_w + shadow_pad * 2
    shadow_h = fit_h + shadow_pad * 2
    shadow_img = Image.new("RGBA", (shadow_w, shadow_h), (0, 0, 0, 0))
    draw_shadow = ImageDraw.Draw(shadow_img)
    draw_shadow.rounded_rectangle(
        [(shadow_pad, shadow_pad), (shadow_pad + fit_w, shadow_pad + fit_h)],
        radius=radius,
        fill=(0, 0, 0, 190),
    )
    shadow_img = shadow_img.filter(ImageFilter.GaussianBlur(radius=20))
    bg.paste(shadow_img, (pos_x - shadow_pad, pos_y - shadow_pad + 10), shadow_img)

    # Paste poster
    bg.paste(fit_poster, (pos_x, pos_y), fit_poster)

    # Crisp subtle poster outline
    border_img = Image.new("RGBA", (fit_w, fit_h), (0, 0, 0, 0))
    draw_border = ImageDraw.Draw(border_img)
    draw_border.rounded_rectangle(
        [(0, 0), (fit_w - 1, fit_h - 1)],
        radius=radius,
        outline=(255, 255, 255, 60),
        width=2,
    )
    bg.paste(border_img, (pos_x, pos_y), border_img)

    # 5. Bottom Branding Badge: G A M E O V E R   M O V I E   H U B
    brand_text = "G A M E O V E R   M O V I E   H U B"
    font_brand = get_system_font(22)
    
    draw_temp = ImageDraw.Draw(bg)
    if font_brand:
        bbox = draw_temp.textbbox((0, 0), brand_text, font=font_brand)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    else:
        text_w = 320
        text_h = 24

    brand_x = (base_w - text_w) // 2
    brand_y = 650

    # Translucent glass badge pill
    badge_pad_x = 28
    badge_pad_y = 9
    badge_rect = [
        (brand_x - badge_pad_x, brand_y - badge_pad_y),
        (brand_x + text_w + badge_pad_x, brand_y + text_h + badge_pad_y),
    ]
    badge_layer = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
    badge_draw = ImageDraw.Draw(badge_layer)
    badge_draw.rounded_rectangle(
        badge_rect,
        radius=16,
        fill=(15, 23, 42, 215),
        outline=(56, 189, 248, 120),
        width=1,
    )
    bg = Image.alpha_composite(bg, badge_layer)

    # Draw brand typography
    draw_final = ImageDraw.Draw(bg)
    if font_brand:
        draw_final.text((brand_x, brand_y), brand_text, font=font_brand, fill=(240, 246, 252, 240))
    else:
        draw_final.text((brand_x, brand_y), brand_text, fill=(240, 246, 252, 240))

    # Save to cached file
    cache_key = hashlib.md5(f"{title}_{len(image_data) if image_data else 'none'}".encode()).hexdigest()[:12]
    out_path = os.path.abspath(os.path.join(DOWNLOADS_DIR, f"thumb_{cache_key}.jpg"))
    final_rgb = bg.convert("RGB")
    final_rgb.save(out_path, "JPEG", quality=95)
    return out_path


async def generate_movie_thumbnail(image_url: str, title: str = "") -> str:
    """
    Downloads the poster asynchronously (with caching) and returns the generated 16:9 thumbnail path (absolute path).
    """
    await download_font()

    # Check cache if URL is known
    if image_url:
        cache_key = hashlib.md5(f"{title}_{image_url}".encode()).hexdigest()[:12]
        cached_file = os.path.abspath(os.path.join(DOWNLOADS_DIR, f"thumb_{cache_key}.jpg"))
        if os.path.exists(cached_file) and os.path.getsize(cached_file) > 5000:
            return cached_file

    image_data = None
    if image_url:
        try:
            image_data = await download_image_bytes(image_url)
        except Exception as e:
            print(f"[Thumbnail] Download error for {image_url}: {e}")

    try:
        out_path = await asyncio.to_thread(generate_movie_thumbnail_sync, image_data, title)
        # Also link URL cache if available
        if image_url:
            cache_key = hashlib.md5(f"{title}_{image_url}".encode()).hexdigest()[:12]
            url_cached_file = os.path.abspath(os.path.join(DOWNLOADS_DIR, f"thumb_{cache_key}.jpg"))
            if not os.path.exists(url_cached_file) and os.path.exists(out_path):
                try:
                    import shutil
                    shutil.copyfile(out_path, url_cached_file)
                except Exception:
                    pass
        return os.path.abspath(out_path)
    except Exception as e:
        print(f"[Thumbnail] Generation error: {e}")
        # Emergency fallback
        try:
            default_img = create_default_movie_poster()
            fallback_path = os.path.abspath(os.path.join(DOWNLOADS_DIR, f"thumb_default_{uuid.uuid4().hex[:6]}.jpg"))
            default_img.save(fallback_path, "JPEG", quality=90)
            return fallback_path
        except Exception:
            return ""
