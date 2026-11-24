"""The floor plan behind the Smart home map: one picture, and where devices sit on it.

Storage is wony.db (helpers/memory_db.py), so Wipe clears it with everything
else. This module is the only way in, and it checks everything: an upload
reaches it as raw bytes, and placements as whatever JSON a caller sent.
"""
import io
import json
import math
import re
import typing

from PIL import Image, ImageOps, UnidentifiedImageError

from helpers import memory_db

# A phone photo is a few MB; anything bigger is not a floor plan.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
# Decoded size is what costs memory. A 48 MP phone photo fits; a bomb does not.
_MAX_PIXELS = 64_000_000
# Plenty to see a plan on a big screen, and keeps the database small.
_MAX_EDGE = 2400
_WEBP_QUALITY = 85
# No SVG: opened on its own it can carry script.
_FORMATS = ["PNG", "JPEG", "WEBP"]

_MAX_PLACEMENTS = 200
_ENTITY_ID = re.compile(r"^[a-z0-9_]{1,64}\.[a-z0-9_]{1,128}$")

_NOT_AN_IMAGE = "That file isn't a PNG, JPG or WebP image."


def save_image(data: bytes) -> None:
    """Keep this picture as the map. Raises ValueError, with a sentence, when it
    cannot be used. Existing placements stay: they are fractions of the picture."""
    try:
        with Image.open(io.BytesIO(data), formats=_FORMATS) as source:
            if source.width * source.height > _MAX_PIXELS:
                raise ValueError("That image is too large. Try a smaller picture.")
            # A big JPEG can decode at half or quarter size, which on a Pi is the
            # difference between seconds and running out of memory.
            source.draft(None, (_MAX_EDGE, _MAX_EDGE))
            source.load()
            # Phones store a sideways picture plus a rotation flag.
            picture = ImageOps.exif_transpose(source)
            picture = picture.convert("RGBA" if picture.has_transparency_data else "RGB")
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError):
        raise ValueError(_NOT_AN_IMAGE) from None

    picture.thumbnail((_MAX_EDGE, _MAX_EDGE))
    encoded = io.BytesIO()
    # Re-encoding also drops the EXIF block, which on a phone photo holds GPS.
    picture.save(encoded, "WEBP", quality=_WEBP_QUALITY)
    memory_db.save_home_map_image(encoded.getvalue(), "image/webp", *picture.size)


def save_placements(raw: typing.Any) -> None:
    """Replace where devices sit. Raises ValueError, with a sentence, on anything
    that is not a list of {entity_id, x, y} with x and y as fractions of the picture."""
    if not isinstance(raw, list):
        raise ValueError("Placements must be a list.")
    if len(raw) > _MAX_PLACEMENTS:
        raise ValueError(f"At most {_MAX_PLACEMENTS} devices fit on the map.")

    # Last one wins, so a device cannot be in two places.
    cleaned: typing.Dict[str, typing.Dict[str, typing.Any]] = {}
    for item in raw:
        entity_id = str(item.get("entity_id", "")) if isinstance(item, dict) else ""
        if not _ENTITY_ID.match(entity_id):
            raise ValueError(f"'{entity_id[:40]}' is not a device id.")
        x, y = item.get("x"), item.get("y")
        if not (_is_fraction(x) and _is_fraction(y)):
            raise ValueError(f"{entity_id} needs x and y as numbers.")
        cleaned[entity_id] = {"entity_id": entity_id, "x": _clamp(x), "y": _clamp(y)}

    if not memory_db.save_home_map_placements(json.dumps(list(cleaned.values()))):
        raise ValueError("Upload a map image first.")


def load() -> typing.Dict[str, typing.Any]:
    row = memory_db.get_home_map()
    if row is None:
        return {"image": None, "placements": []}
    return {
        # The version in the URL is what makes a replaced picture show up
        # despite the browser's cache.
        "image": {
            "url": f"/api/devices/map/image?v={int(row['updated'] * 1000)}",
            "width": row["width"],
            "height": row["height"],
        },
        "placements": json.loads(row["placements"]),
    }


def image() -> typing.Optional[typing.Tuple[bytes, str]]:
    """The stored picture and its media type."""
    row = memory_db.get_home_map()
    return (row["image"], row["mime"]) if row else None


def delete() -> None:
    memory_db.delete_home_map()


def _is_fraction(value: typing.Any) -> bool:
    # bool is an int in Python, and True is not a position.
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 4)
