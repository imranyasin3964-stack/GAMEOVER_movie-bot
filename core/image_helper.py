import os

async def get_16_9_thumbnail(url: str, song_title: str) -> str:
    """
    Downloads an image and converts it into a 16:9 cinematic widescreen thumbnail
    with blurred backdrop, fitted center poster, drop shadow, and clean GameOver Movie Hub branding.
    Delegates directly to core.thumbnail.generate_movie_thumbnail.
    """
    try:
        from core.thumbnail import generate_movie_thumbnail
        thumb_path = await generate_movie_thumbnail(url, song_title)
        if thumb_path and os.path.exists(thumb_path):
            return os.path.abspath(thumb_path)
    except Exception as e:
        print(f"[Thumbnail] Generation skipped: {e}")

    return url or "https://images.unsplash.com/photo-1489599849927-2ee91cede3ba?q=80&w=1280"

