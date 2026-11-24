"""The floor plan behind the Smart home map: one picture, and where devices sit on it.

Storage is wony.db (helpers/memory_db.py), so Wipe clears it with everything
else. This module is the only way in, and it checks everything: a picture
reaches it as bytes from a file on this device, and placements as whatever JSON
a caller sent.

The panel has no file picker and its API answers only on this machine, so a
picture comes from a folder on the device: sources() lists them and the caller
names one by id, never by path.
"""
import hashlib
import io
import json
import math
import os
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

_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")
_MAX_SOURCES = 40


class _Source(typing.NamedTuple):
    id: str
    name: str
    place: str
    size: int
    modified: float
    path: str


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
        raise ValueError("Choose a map picture first.")


def _places() -> typing.List[typing.Tuple[str, str]]:
    """(label, folder) for each place a picture is likely to be, that exists:
    the user's own folders, and whatever a USB stick is mounted as."""
    home = os.path.expanduser("~")
    user = os.path.basename(home)
    places = [(name, os.path.join(home, name)) for name in ("Pictures", "Downloads", "Desktop")]
    for root in (f"/media/{user}", f"/run/media/{user}", "/mnt"):
        try:
            mounts = sorted(os.listdir(root))
        except OSError:
            continue
        places += [(name, os.path.join(root, name)) for name in mounts]
    return [(label, folder) for label, folder in places if os.path.isdir(folder)]


def _found() -> typing.List[_Source]:
    found = []
    for label, folder in _places():
        try:
            entries = list(os.scandir(folder))
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith(".") or not entry.name.lower().endswith(_SUFFIXES):
                continue
            try:
                # A link could point anywhere, so only real files count.
                if not entry.is_file(follow_symlinks=False):
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if info.st_size > MAX_UPLOAD_BYTES:
                continue
            source_id = hashlib.sha1(entry.path.encode("utf-8", "replace")).hexdigest()[:16]
            found.append(_Source(source_id, entry.name, label, info.st_size, info.st_mtime, entry.path))
    found.sort(key=lambda s: s.modified, reverse=True)
    return found[:_MAX_SOURCES]


def sources() -> typing.List[typing.Dict[str, typing.Any]]:
    """Pictures that could become the map, newest first. No paths: an id is how
    a caller picks one, so a request cannot name a file of its own."""
    return [
        {"id": s.id, "name": s.name, "place": s.place, "size": s.size}
        for s in _found()
    ]


def import_source(source_id: str) -> None:
    """Use one of sources() as the map. Raises ValueError, with a sentence."""
    chosen = next((s for s in _found() if s.id == source_id), None)
    if chosen is None:
        raise ValueError("That picture isn't there any more. Refresh the list.")
    try:
        with open(chosen.path, "rb") as fh:
            data = fh.read(MAX_UPLOAD_BYTES + 1)
    except OSError:
        raise ValueError("Could not read that picture.") from None
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("That picture is too big. The limit is 15 MB.")
    save_image(data)


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
