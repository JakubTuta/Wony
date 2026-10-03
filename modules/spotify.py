import base64
import datetime
import http.server
import os
import socketserver
import time
import typing
import urllib.parse
import webbrowser

import requests

from helpers import net
from helpers.cache import Cache
from helpers.decorators import capture_response, retry_on_unauthorized, treat_as_answer
from helpers.logger import logger
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement

auth_code = None


class DeviceGone(Exception):
    """Spotify answered 404: the device we aimed at is not there any more."""


class AuthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global auth_code

        # Parse the query parameters
        query_components = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if "code" in query_components:
            auth_code = query_components["code"][0]

            # Send a simple response back to the browser
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication successful!</h1><p>You can close this window now.</p></body></html>"
            )
            # No explicit shutdown needed — _get_auth_code() polls via
            # handle_request() and exits its loop as soon as auth_code is set.
        else:
            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h1>Authentication failed</h1></body></html>"
            )


@register_service(
    module_name="spotify",
    requires=Requirement(
        env_vars=["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"],
        setup_hint=(
            "Create a free app at developer.spotify.com/dashboard, set its Redirect URI "
            "to http://127.0.0.1:8888/callback, then paste its client ID and secret here."
        ),
    ),
)
class Spotify:
    """Spotify service for music playback control."""

    ENV_SPOTIFY_CLIENT_ID = "SPOTIFY_CLIENT_ID"
    ENV_SPOTIFY_CLIENT_SECRET = "SPOTIFY_CLIENT_SECRET"
    SPOTIFY_OAUTH_ACCESS_KEY = "SPOTIFY_OAUTH_ACCESS_KEY"
    SPOTIFY_OAUTH_REFRESH_KEY = "SPOTIFY_OAUTH_REFRESH_KEY"
    SPOTIFY_OAUTH_EXPIRATION_DATE = "SPOTIFY_OAUTH_EXPIRATION_DATE"

    PORT = 8888
    REDIRECT_URI = f"http://127.0.0.1:{PORT}/callback"
    SCOPE = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private user-library-modify user-library-read"

    def __init__(self):
        self.albums = {}

        self.client_id = os.getenv(self.ENV_SPOTIFY_CLIENT_ID)
        self.client_secret = os.getenv(self.ENV_SPOTIFY_CLIENT_SECRET)

        self.access_token, self.refresh_token = self._get_tokens_from_cache()

        if not self.access_token or not self.refresh_token:
            from helpers.registry import ServiceRegistry
            if not ServiceRegistry.interactive_allowed():
                raise Exception("Spotify needs interactive OAuth — run a Spotify command to authorize.")

            self.auth_code = self._get_auth_code()
            if not self.auth_code:
                raise Exception("Failed to get authorization code")

            self.access_token, self.refresh_token = self._get_tokens()
            if not self.access_token or not self.refresh_token:
                raise Exception("Failed to get access token and refresh token")

        # Resolved on first use, not here: Spotify being closed at startup must
        # not stop the module registering, or every music command stays missing
        # until the app is restarted.
        self.device_id: typing.Optional[str] = None

    @capture_response(mute=True, one_message=True)
    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def play_songs(
        self,
        title: str,
        artist: str,
        content_type: typing.Literal["", "track", "album", "artist", "playlist"] = "",
    ) -> typing.Optional[str]:
        """
        [SPOTIFY JOB] Plays music on Spotify: a song, an album, everything by an artist,
        or one of the user's own playlists. With no title and no artist it just resumes
        whatever was playing.

        Args:
            title (str): Title of the song, album or playlist to play, or the artist's
                name if no album/song is specified. (required)
            artist (str): Artist of the song to play, if not specified by user then set to empty string (""). (required)
            content_type (str): Type of content to play - "track" for a single song, "album" for a full album,
                               "artist" for all music by an artist, "playlist" for one of the user's playlists.
                               Leave empty to use first found result.
                               Infer from user intent: "play song X" → "track", "play album X" → "album",
                               "play all music by X" / "play everything by X" → "artist",
                               "play my X playlist" → "playlist"

        Returns:
            str: Success message with track/album details or error message if not found.
        """

        if not title and not artist:
            self._transport("put", "https://api.spotify.com/v1/me/player/play")
            return "Playback resumed."

        if (content_type or "").strip().lower() == "playlist":
            return self._play_playlist(title or artist)

        search_response = self._search(query=title, artist=artist, content_type=content_type)

        if not search_response:
            # This job is mute=True (music starting IS the feedback) — a soft
            # "not found" return would be silently swallowed just like a real
            # success. Raise instead so the always-spoken error path fires.
            raise Exception(f"Could not find '{title}'" + (f" by {artist}" if artist else "") + ".")

        songs = self._get_songs_from_search(search_response)

        self._set_shuffle(False)
        self._device_call(
            "put", "https://api.spotify.com/v1/me/player/play", json={"uris": songs}
        )
        if search_response.get("type") == "artists":
            return f"Playing {search_response['name']}."
        return f"Playing {search_response['name']} by {search_response['artist']}."

    @capture_response
    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def add_to_queue(self, title: str, artist: str) -> str:
        """
        [SPOTIFY SERVICE METHOD] Adds songs or albums to the Spotify playback queue for later listening.
        This service method searches for music content and adds it to the current playback queue
        without interrupting the currently playing track.

        Args:
            title (str): Title of the song or an album to add, or name of the artist if no album/song is specified. (required)
            artist (str): Artist of the song to add, if not specified by user then set to empty string (""). (required)

        Returns:
            None: Specified music will be added to the Spotify queue.
        """

        search_response = self._search(query=title, artist=artist)

        if not search_response:
            return f"Could not find '{title}'" + (f" by {artist}" if artist else "") + "."

        songs = self._get_songs_from_search(search_response)

        for song in songs:
            self._device_call(
                "post",
                f"https://api.spotify.com/v1/me/player/queue?uri={urllib.parse.quote(song)}",
                "&",
            )

        return f"Added {search_response['name']} by {search_response['artist']} to the queue."







    # ------------------------------------------------------------------
    # Transport / volume / like primitives
    # ------------------------------------------------------------------

    @retry_on_unauthorized("_refresh_access_token")
    def _transport(self, verb: str, path: str, sep: str = "?") -> None:
        self._device_call(verb, path, sep)

    # Spotify's state endpoint lags a beat behind a volume write, so a
    # confirmation read gets a couple of chances before the write counts as
    # not having landed.
    _VOLUME_CONFIRM_TRIES = 3
    _VOLUME_CONFIRM_DELAY = 0.35
    _VOLUME_STEP = 10

    def _volume_device(self) -> typing.Dict[str, typing.Any]:
        """The device volume commands must read from and write to.

        Resolved live every time: self.device_id is cached for the whole
        session, so once playback moves to another Spotify device a relative
        change would read the new device's level and write it back to the old
        one — the request succeeds and nothing gets louder.
        """
        device = (self._get_playback_state() or {}).get("device") or {}
        if not device.get("id"):
            # mute=True job — raise so the always-spoken error path fires
            # instead of a soft-fail string being swallowed like a success.
            raise Exception(
                "Nothing is playing — open Spotify on your phone or computer and try again."
            )
        self.device_id = device["id"]
        return device

    def _adjust_volume(self, delta: int) -> str:
        """Relative change, read and written on the same live device."""
        device = self._volume_device()
        current = device.get("volume_percent")
        if current is None:
            raise Exception(
                f"{device.get('name') or 'That device'} does not report its volume, "
                "so it cannot be turned up or down — say an exact level instead."
            )
        return self._apply_volume(max(0, min(int(current) + delta, 100)), device)

    def _report_volume(self) -> str:
        # A question, not the muted action this job normally performs.
        treat_as_answer()
        device = self._volume_device()
        current = device.get("volume_percent")
        if current is None:
            return f"{device.get('name') or 'That device'} does not report a volume."
        name = device.get("name")
        return f"Spotify volume is {int(current)}%" + (f" on {name}." if name else ".")

    @retry_on_unauthorized("_refresh_access_token")
    def _apply_volume(
        self, volume: int, device: typing.Optional[typing.Dict[str, typing.Any]] = None
    ) -> str:
        if not 0 <= volume <= 100:
            raise Exception("Volume must be between 0 and 100.")

        if device is None:
            device = self._volume_device()
        if device.get("supports_volume") is False:
            name = device.get("name") or "That device"
            raise Exception(
                f"{name} does not accept volume changes from Spotify — "
                "use its own volume control."
            )

        before = device.get("volume_percent")
        # Pinned to the device we just read, not _device_call's cached id: its
        # 404 retry can re-target another device, which would leave `before`
        # and the confirmation below describing something else.
        self._make_spotify_request(
            "put",
            "https://api.spotify.com/v1/me/player/volume"
            f"?volume_percent={volume}&device_id={device['id']}",
        )

        landed = self._confirm_volume(volume)
        if landed is None or landed == volume:
            return f"Volume set to {volume}%."
        if before is not None and landed != int(before):
            # Some speakers snap to their own steps — it moved, just not exactly.
            return f"Volume set to {landed}%."
        raise Exception(
            f"Spotify would not change the volume — {device.get('name') or 'the device'} "
            f"is still at {landed}%."
        )

    def _confirm_volume(self, expected: int) -> typing.Optional[int]:
        """Volume Spotify reports after a write, or None if it reports none."""
        level: typing.Optional[int] = None
        for attempt in range(self._VOLUME_CONFIRM_TRIES):
            if attempt:
                time.sleep(self._VOLUME_CONFIRM_DELAY)
            device = (self._get_playback_state() or {}).get("device") or {}
            raw = device.get("volume_percent")
            if raw is None:
                return None
            level = int(raw)
            if level == expected:
                return level
        return level

    @retry_on_unauthorized("_refresh_access_token")
    def _set_liked(self, liked: bool) -> str:
        track_id = self._get_current_track_id()
        if not track_id:
            return "Nothing is currently playing."
        self._make_spotify_request(
            "put" if liked else "delete",
            f"https://api.spotify.com/v1/me/tracks?ids={track_id}",
        )
        state = self._get_playback_state()
        name = state["item"]["name"] if state and state.get("item") else "Track"
        return f"Liked {name}." if liked else f"Removed {name} from liked songs."

    @capture_response(mute=True, one_message=True)
    @method_job
    def control_playback(
        self,
        action: typing.Literal[
            "toggle", "play", "pause", "next", "previous", "restart",
            "seek", "shuffle", "repeat", "like", "unlike", "transfer",
        ] = "toggle",
        value: str = "",
    ) -> str:
        """
        [SPOTIFY JOB] Controls Spotify playback: play, pause, skip, go back, restart,
        jump to a position, shuffle, repeat, like or unlike the current song, or move
        playback to another device. This is the single tool for all of those.

        Args:
            action (str): One of: toggle (play/pause depending on current state,
                the default), play, pause, next, previous, restart, seek, shuffle,
                repeat, like, unlike, transfer.
            value (str): Only for two actions — the position in seconds for "seek",
                and the device name to play on for "transfer".

        Returns:
            str: Confirmation of what changed.
        """
        act = (action or "toggle").strip().lower()

        if act == "toggle":
            act = "pause" if self._is_playback_playing() else "play"

        if act in ("like", "save", "favorite", "favourite"):
            return self._set_liked(True)
        if act in ("unlike", "unsave", "dislike"):
            return self._set_liked(False)
        if act == "seek":
            return self._seek(value)
        if act == "repeat":
            return self._cycle_repeat()
        if act == "transfer":
            return self._transfer_playback(value)

        if act in ("play", "resume", "start"):
            self._transport("put", "https://api.spotify.com/v1/me/player/play")
            return "Playback resumed."
        if act in ("pause", "stop"):
            self._transport("put", "https://api.spotify.com/v1/me/player/pause")
            return "Playback paused."
        if act in ("next", "skip"):
            self._transport("post", "https://api.spotify.com/v1/me/player/next")
            return "Skipped to next song."
        if act in ("previous", "prev", "back"):
            self._transport("post", "https://api.spotify.com/v1/me/player/previous")
            return "Playing previous song."
        if act in ("restart", "replay"):
            self._transport(
                "put", "https://api.spotify.com/v1/me/player/seek?position_ms=0", "&"
            )
            return "Restarted song from the beginning."
        if act == "shuffle":
            state = self._get_playback_state()
            if not state:
                raise Exception("No active Spotify device.")
            return self._set_shuffle(not state.get("shuffle_state", False))

        raise Exception(
            f"Unknown action '{action}'. Use toggle, play, pause, next, previous, "
            "restart, seek, shuffle, repeat, like, unlike or transfer."
        )

    def _seek(self, value: str) -> str:
        try:
            seconds = max(0, int(float(value)))
        except (TypeError, ValueError):
            raise Exception("Seek needs a position in seconds, e.g. value='90'.") from None
        self._device_call(
            "put",
            f"https://api.spotify.com/v1/me/player/seek?position_ms={seconds * 1000}",
            "&",
        )
        return f"Jumped to {seconds // 60}:{seconds % 60:02d}."

    # Spotify's repeat is a three-state field, not a toggle; cycling is what a
    # user pressing the button expects.
    _REPEAT_CYCLE = {"off": "context", "context": "track", "track": "off"}
    _REPEAT_SAID = {"off": "Repeat off.", "context": "Repeating the album.",
                    "track": "Repeating this song."}

    def _cycle_repeat(self) -> str:
        state = self._get_playback_state()
        if not state:
            raise Exception("No active Spotify device.")
        wanted = self._REPEAT_CYCLE.get(state.get("repeat_state", "off"), "context")
        self._device_call(
            "put", f"https://api.spotify.com/v1/me/player/repeat?state={wanted}", "&"
        )
        return self._REPEAT_SAID[wanted]

    def _transfer_playback(self, name: str) -> str:
        if not name:
            raise Exception("Say which device to play on, e.g. value='phone'.")
        needle = name.strip().lower()
        devices = self._devices()
        match = next((d for d in devices if needle in d.get("name", "").lower()), None)
        if match is None:
            known = ", ".join(d.get("name", "?") for d in devices) or "none"
            raise Exception(f"No Spotify device called '{name}'. Available: {known}.")
        self._make_spotify_request(
            "put",
            "https://api.spotify.com/v1/me/player",
            json={"device_ids": [match["id"]], "play": True},
        )
        # The old device id is stale the moment playback moves.
        self.device_id = match["id"]
        return f"Playing on {match['name']}."

    @capture_response(mute=True, one_message=True)
    @method_job
    def set_volume(
        self,
        level: int = -1,
        direction: typing.Literal["", "up", "down", "max", "min", "get"] = "",
    ) -> str:
        """
        [SPOTIFY JOB] Sets, adjusts, or reports the Spotify playback volume. Call this
        for anything about volume, every time, even if the volume was already discussed:
        the user can change it in the Spotify app between messages, so a level mentioned
        earlier in the conversation is not the current one. For a relative change pass
        direction and let this job read the real level — never work out the target
        number yourself.

        Args:
            level (int): Target volume 0-100. Use this for "set volume to 40".
            direction (str): Relative change instead of a level: up or down (10%
                steps), max (100), min (0), or get to report the current volume
                without changing it.

        Returns:
            str: The new volume, or the current one for "get".
        """
        move = (direction or "").strip().lower()
        if move in ("get", "check", "current", "status", "read"):
            return self._report_volume()
        if move in ("up", "louder", "increase"):
            return self._adjust_volume(self._VOLUME_STEP)
        if move in ("down", "quieter", "decrease", "lower"):
            return self._adjust_volume(-self._VOLUME_STEP)
        if move in ("max", "maximum", "full"):
            return self._apply_volume(100)
        if move in ("min", "minimum", "mute"):
            return self._apply_volume(0)

        try:
            target = int(level)
        except (TypeError, ValueError):
            raise Exception("Invalid volume value.")
        if target < 0:
            raise Exception("Provide a volume level 0-100, or a direction.")
        return self._apply_volume(target)

    @capture_response
    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def spotify_info(
        self,
        what: typing.Literal["current", "queue", "playlists", "devices", "search"] = "current",
        query: str = "",
    ) -> str:
        """
        [SPOTIFY JOB] Reports what Spotify is doing or knows: the song playing now, what
        is queued next, the user's playlists, the devices they can play on, or the
        results of a search.

        Args:
            what (str): "current" (the default), "queue", "playlists", "devices"
                or "search".
            query (str): What to search for. (required for "search")

        Returns:
            str: The requested information.
        """
        wanted = (what or "current").strip().lower()

        if wanted in ("current", "track", "now", "playing"):
            return self._describe_current()
        if wanted == "queue":
            return self._describe_queue()
        if wanted in ("playlists", "playlist"):
            playlists = self._get_user_playlists()
            if not playlists:
                return "No playlists found."
            return "Your playlists:\n" + "\n".join(f"  {p['name']}" for p in playlists)
        if wanted in ("devices", "device"):
            return self._describe_devices()
        if wanted == "search":
            if not query:
                return "Error: 'query' is required for a search."
            found = self._search(query=query)
            if not found:
                return f"Nothing on Spotify matches '{query}'."
            kind = found.get("type", "").rstrip("s") or "result"
            artist = found.get("artist", "")
            return f"Found {kind}: {found['name']}" + (f" by {artist}." if artist else ".")

        return f"Unknown option '{what}'. Use current, queue, playlists, devices or search."

    def _describe_current(self) -> str:
        state = self._get_playback_state()
        if not state or "item" not in state or state.get("item") is None:
            result = "Nothing is currently playing on Spotify."
        else:
            item = state["item"]
            name = item.get("name", "Unknown")
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            result = f"Now playing: {name}" + (f" by {artists}" if artists else "") + "."

        return result

    @retry_on_unauthorized("_refresh_access_token")
    def playback_snapshot(self) -> typing.Dict[str, typing.Any]:
        """Playback state as data, for the now-playing panel.

        Not a job: spotify_info says the same thing in a sentence, and a
        progress bar needs numbers a sentence cannot carry.
        """
        state = self._get_playback_state()
        item = (state or {}).get("item")
        if not state or not item:
            return {"active": False}

        images = item.get("album", {}).get("images", [])
        # Spotify returns 640/300/64 px. The middle one is the right size for a
        # panel and a third of the bytes.
        art = images[1] if len(images) > 1 else (images[0] if images else None)

        device = state.get("device") or {}
        return {
            "active": True,
            "is_playing": bool(state.get("is_playing")),
            "title": item.get("name", ""),
            "artist": ", ".join(a["name"] for a in item.get("artists", [])),
            "album": item.get("album", {}).get("name", ""),
            "art_url": art.get("url") if art else None,
            "progress_ms": state.get("progress_ms") or 0,
            "duration_ms": item.get("duration_ms") or 0,
            "shuffle": bool(state.get("shuffle_state")),
            "device": device.get("name", ""),
            "volume": device.get("volume_percent"),
        }

    def _play_playlist(self, name: str) -> str:
        match = self._find_playlist(name)
        if not match:
            # play_songs is mute=True — raise so the always-spoken error path
            # fires instead of a soft-fail string being swallowed as success.
            raise Exception(f"Playlist '{name}' not found.")

        self._device_call(
            "put",
            "https://api.spotify.com/v1/me/player/play",
            json={"context_uri": match["uri"]},
        )
        return f"Playing playlist {match['name']}."

    def _find_playlist(self, name: str) -> typing.Optional[typing.Dict[str, str]]:
        needle = (name or "").lower()
        return next(
            (p for p in self._get_user_playlists() if needle in p["name"].lower()), None
        )

    @capture_response
    @retry_on_unauthorized("_refresh_access_token")
    @method_job(confirms=True)
    def manage_playlist(
        self,
        action: typing.Literal["add", "remove", "create", "delete"] = "add",
        playlist_name: str = "",
        title: str = "",
        artist: str = "",
    ) -> str:
        """
        [SPOTIFY JOB] Changes a playlist: puts a song in it, takes one out, makes a new
        one, or deletes one. With no song named, the song playing right now is used.

        Args:
            action (str): "add" (the default), "remove", "create" or "delete".
            playlist_name (str): Full or partial name of the playlist. (required)
            title (str): Title of the song. Leave empty to use the song playing now.
            artist (str): Artist of the song, used to narrow the search.

        Returns:
            str: Confirmation message or error.
        """
        wanted = (action or "add").strip().lower()
        if not playlist_name:
            return "Error: playlist_name is required."

        if wanted == "create":
            return self._create_playlist(playlist_name)
        if wanted in ("delete", "remove_playlist"):
            return self._delete_playlist(playlist_name)
        if wanted not in ("add", "remove"):
            return f"Unknown action '{action}'. Use add, remove, create or delete."

        playlist = self._find_playlist(playlist_name)
        if not playlist:
            return f"Playlist '{playlist_name}' not found."

        resolved = self._resolve_track(title, artist)
        if isinstance(resolved, str):
            return resolved
        uris, track_label = resolved

        if wanted == "add":
            self._make_spotify_request(
                "post",
                f"https://api.spotify.com/v1/playlists/{playlist['id']}/tracks",
                json={"uris": uris},
            )
            return f"Added {track_label} to {playlist['name']}."

        self._make_spotify_request(
            "delete",
            f"https://api.spotify.com/v1/playlists/{playlist['id']}/tracks",
            json={"tracks": [{"uri": uri} for uri in uris]},
        )
        return f"Removed {track_label} from {playlist['name']}."

    def _resolve_track(
        self, title: str, artist: str
    ) -> typing.Union[str, typing.Tuple[typing.List[str], str]]:
        """(uris, label) for the named song, or the song playing now. A plain
        string is the reason it could not be resolved."""
        if title:
            found = self._search(query=title, artist=artist, content_type="track")
            if not found:
                return f"Could not find '{title}'" + (f" by {artist}" if artist else "") + "."
            return self._get_songs_from_search(found), f"{found['name']} by {found['artist']}"

        track_id = self._get_current_track_id()
        if not track_id:
            return "Nothing is currently playing."
        state = self._get_playback_state()
        item = state.get("item", {}) if state else {}
        return [f"spotify:track:{track_id}"], item.get("name", "Current track")

    def _create_playlist(self, name: str) -> str:
        me = self._make_spotify_request("get", "https://api.spotify.com/v1/me").json()
        created = self._make_spotify_request(
            "post",
            f"https://api.spotify.com/v1/users/{me['id']}/playlists",
            json={"name": name, "public": False},
        ).json()
        return f"Created playlist '{created.get('name', name)}'."

    def _delete_playlist(self, name: str) -> str:
        playlist = self._find_playlist(name)
        if not playlist:
            return f"Playlist '{name}' not found."
        # Spotify has no delete: unfollowing your own playlist is what the app's
        # "Delete" button does, and it is what makes it disappear from the list.
        self._make_spotify_request(
            "delete",
            f"https://api.spotify.com/v1/playlists/{playlist['id']}/followers",
        )
        return f"Deleted playlist '{playlist['name']}'."


    def _set_shuffle(self, state: bool) -> str:
        base_url = (
            f"https://api.spotify.com/v1/me/player/shuffle?state={str(state).lower()}"
        )
        self._device_call("put", base_url, "&")
        return f"Shuffle {'enabled' if state else 'disabled'}."

    def _get_current_track_id(self) -> typing.Optional[str]:
        state = self._get_playback_state()
        if state and state.get("item"):
            return state["item"]["id"]
        return None

    def _get_user_playlists(self) -> typing.List[typing.Dict[str, str]]:
        playlists = []
        url = "https://api.spotify.com/v1/me/playlists?limit=50"
        while url:
            response = self._make_spotify_request("get", url)
            data = response.json()
            for item in data.get("items", []):
                playlists.append({"name": item["name"], "id": item["id"], "uri": item["uri"]})
            url = data.get("next")
        return playlists

    def _get_auth_headers(self) -> typing.Dict[str, str]:
        """Get authorization headers for API requests"""
        return {"Authorization": f"Bearer {self.access_token}"}

    def _get_basic_auth_header(self) -> str:
        """Get basic auth header for token requests"""
        return base64.b64encode(
            f"{self.client_id}:{self.client_secret}".encode()
        ).decode()

    def _build_url_with_device(self, base_url: str, separator: str = "?") -> str:
        """Build URL with device_id parameter if available"""
        if not self.device_id:
            self.device_id = self._get_active_devices()
        if self.device_id:
            return f"{base_url}{separator}device_id={self.device_id}"
        return base_url

    def _device_call(
        self, method: str, base_url: str, separator: str = "?", **kwargs
    ) -> typing.Optional[requests.Response]:
        """A player request aimed at the active device.

        Spotify forgets a device as soon as its app closes, and the id is then
        dead for the rest of the session. Re-resolving once on 404 is what makes
        "play something" work again after reopening Spotify, instead of failing
        until Wony itself is restarted.
        """
        try:
            return self._make_spotify_request(
                method, self._build_url_with_device(base_url, separator), **kwargs
            )
        except DeviceGone:
            self.device_id = self._get_active_devices()
            if not self.device_id:
                raise Exception(
                    "No Spotify device is available — open Spotify on your phone "
                    "or computer and try again."
                ) from None
            return self._make_spotify_request(
                method, self._build_url_with_device(base_url, separator), **kwargs
            )

    def _make_spotify_request(
        self, method: str, url: str, **kwargs
    ) -> requests.Response:
        """Make a Spotify API request with standard headers and error handling"""
        headers = kwargs.pop("headers", self._get_auth_headers())
        try:
            response = getattr(net, method.lower())(url, headers=headers, **kwargs)
        except requests.exceptions.Timeout as e:
            # A bare "Read timed out" is meaningless when shown on the
            # now-playing card or spoken aloud, and the panel polls again in
            # a few seconds anyway — no retry needed here.
            raise Exception("Spotify didn't respond in time — try again in a moment.") from e
        except requests.exceptions.ConnectionError as e:
            raise Exception("Could not reach Spotify — check your internet connection.") from e
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            # Bare "404 Client Error: Not Found for url: ..." is meaningless when
            # spoken aloud — translate the common cases so capture_response's
            # always-vocalized error path actually tells the user something.
            # 401/403 are left as HTTPError so retry_on_unauthorized can still
            # catch them and attempt a token refresh.
            status = response.status_code
            if status == 404:
                raise DeviceGone(
                    "Spotify device is no longer available — open Spotify and try again."
                ) from e
            if status == 429:
                raise Exception("Spotify is rate-limiting requests — try again in a moment.") from e
            raise
        return response

    def _is_playback_playing(self):
        playback_state = self._get_playback_state()

        if playback_state and "is_playing" in playback_state:
            return playback_state["is_playing"]

        return False

    def _get_playback_state(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        response = self._make_spotify_request(
            "get", "https://api.spotify.com/v1/me/player"
        )
        # Nothing playing is a 204 with an empty body — a success, so it never
        # raised HTTPError, and .json() blew up on the empty string instead.
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    @retry_on_unauthorized("_refresh_access_token")
    def _devices(self) -> typing.List[typing.Dict[str, typing.Any]]:
        response = self._make_spotify_request(
            "get", "https://api.spotify.com/v1/me/player/devices"
        )
        return response.json().get("devices", [])

    def _get_active_devices(self) -> typing.Optional[str]:
        devices = self._devices()
        if not devices:
            return None

        # Find active device or use first available
        active_device = next(
            (device for device in devices if device["is_active"]), devices[0]
        )
        return active_device.get("id")

    def _describe_devices(self) -> str:
        devices = self._devices()
        if not devices:
            return "No Spotify devices are available — open Spotify somewhere first."
        lines = [f"{len(devices)} Spotify device(s):"]
        for device in devices:
            mark = " (playing here)" if device.get("is_active") else ""
            lines.append(f"  {device.get('name', '?')} — {device.get('type', '?')}{mark}")
        return "\n".join(lines)

    def _describe_queue(self) -> str:
        response = self._make_spotify_request(
            "get", "https://api.spotify.com/v1/me/player/queue"
        )
        if response.status_code == 204 or not response.content:
            return "Nothing is queued."
        queued = response.json().get("queue", [])[:10]
        if not queued:
            return "Nothing is queued."
        lines = [f"Next up ({len(queued)}):"]
        for item in queued:
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            lines.append(f"  {item.get('name', '?')}" + (f" — {artists}" if artists else ""))
        return "\n".join(lines)

    def _refresh_access_token(self, refresh_token):
        headers = {
            "Authorization": f"Basic {self._get_basic_auth_header()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

        response = net.post(
            "https://accounts.spotify.com/api/token", headers=headers, data=data
        )

        if response.status_code == 200:
            token_info = response.json()
            self.access_token = token_info["access_token"]
            # Spotify may hand back a rotated refresh token; keep the old one
            # when it does not. Without this write-back the cached token stayed
            # permanently expired, so every process start burned a refresh call.
            self.refresh_token = token_info.get("refresh_token") or refresh_token
            self._save_tokens(
                self.access_token,
                self.refresh_token,
                token_info.get("expires_in"),
            )
            return self.access_token
        else:
            self.access_token = None
            return None

    def _get_tokens_from_cache(self):
        access_token = Cache.get_value(self.SPOTIFY_OAUTH_ACCESS_KEY)
        refresh_token = Cache.get_value(self.SPOTIFY_OAUTH_REFRESH_KEY)
        expiration_date = Cache.get_value(self.SPOTIFY_OAUTH_EXPIRATION_DATE)

        if access_token and refresh_token and expiration_date:
            try:
                expiration_datetime = datetime.datetime.fromisoformat(expiration_date)

                if expiration_datetime > datetime.datetime.now():
                    return access_token, refresh_token

                else:
                    access_token = self._refresh_access_token(refresh_token)

                    if access_token:
                        return access_token, refresh_token

            except (ValueError, TypeError):
                pass

        return None, None

    _AUTH_TIMEOUT_SECONDS = 180

    def _get_auth_code(self):
        global auth_code
        auth_code = None

        auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.REDIRECT_URI,
                "scope": self.SCOPE,
                "show_dialog": "true",
            }
        )

        logger.log_system_event("spotify_auth", f"Opening browser for authorization.")
        webbrowser.open(auth_url)

        httpd = socketserver.TCPServer(("127.0.0.1", self.PORT), AuthHandler)
        httpd.timeout = 1.0  # bounds each handle_request() call so the deadline loop below is enforced
        logger.log_system_event("spotify_auth", f"Waiting for authorization at http://localhost:{self.PORT}")
        try:
            deadline = time.monotonic() + self._AUTH_TIMEOUT_SECONDS
            while auth_code is None and time.monotonic() < deadline:
                httpd.handle_request()
        finally:
            httpd.server_close()

        if not auth_code:
            logger.log_error("Spotify authorization timed out.", "spotify.auth")
        return auth_code

    def _get_tokens(self):
        headers = {
            "Authorization": f"Basic {self._get_basic_auth_header()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {
            "grant_type": "authorization_code",
            "code": self.auth_code,
            "redirect_uri": self.REDIRECT_URI,
        }

        response = net.post(
            "https://accounts.spotify.com/api/token", headers=headers, data=data
        )

        if response.status_code == 200:
            token_info = response.json()
            self.access_token = token_info["access_token"]
            self.refresh_token = token_info["refresh_token"]
            self._save_tokens(
                self.access_token, self.refresh_token, token_info.get("expires_in")
            )
            return self.access_token, self.refresh_token
        else:
            self.access_token = None
            self.refresh_token = None
            return None, None

    def _save_tokens(self, access_token, refresh_token, expires_in=None):
        try:
            lifetime = int(expires_in)
        except (TypeError, ValueError):
            lifetime = 3600
        expiration_date = datetime.datetime.now() + datetime.timedelta(seconds=lifetime)
        Cache.set_value(self.SPOTIFY_OAUTH_ACCESS_KEY, access_token)
        Cache.set_value(self.SPOTIFY_OAUTH_REFRESH_KEY, refresh_token)
        Cache.set_value(self.SPOTIFY_OAUTH_EXPIRATION_DATE, expiration_date.isoformat())

    @retry_on_unauthorized("_refresh_access_token")
    def _search(
        self, query: str, artist: str = "", content_type: str = ""
    ) -> typing.Optional[typing.Dict[str, typing.Any]]:
        final_query = query or artist

        # Map user-facing type to Spotify API type param and search order
        TYPE_MAP = {
            "track": ("track", ["tracks"]),
            "album": ("album", ["albums"]),
            "artist": ("artist", ["artists"]),
        }
        if content_type in TYPE_MAP:
            api_type, search_order = TYPE_MAP[content_type]
        else:
            api_type = "album,track,artist"
            search_order = ["albums", "tracks", "artists"]

        url = f"https://api.spotify.com/v1/search?q={urllib.parse.quote(final_query)}&limit=10&type={urllib.parse.quote(api_type)}"
        response = self._make_spotify_request("get", url)
        response_data = response.json()

        for result_type in search_order:
            if result_type in ("albums", "tracks"):
                if result_type not in response_data:
                    continue

                items = response_data[result_type]["items"]
                if not items:
                    continue

                if artist:
                    for item in items:
                        if any(
                            a["name"].lower() == artist.lower() for a in item["artists"]
                        ):
                            found_item = item
                            break
                    else:
                        continue
                else:
                    found_item = items[0]

                return {
                    "uri": found_item["uri"],
                    "name": found_item["name"],
                    "artist": artist or found_item["artists"][0]["name"],
                    "type": result_type,
                }

            elif result_type == "artists":
                if "artists" not in response_data:
                    return None

                items = response_data["artists"]["items"]
                if not items:
                    return None

                return {
                    "uri": items[0]["uri"],
                    "id": items[0]["id"],
                    "name": items[0]["name"],
                    "type": "artists",
                }

        return None

    def _get_tracks_from_album(self, album_id: str) -> typing.List[str]:
        url = f"https://api.spotify.com/v1/albums/{album_id}"

        try:
            response = self._make_spotify_request("get", url)
            album_data = response.json()
            return [track["uri"] for track in album_data["tracks"]["items"]]
        except requests.exceptions.HTTPError:
            return []

    def _get_artists_top_tracks(self, artist_id: str) -> typing.List[str]:
        url = f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks"

        try:
            response = self._make_spotify_request("get", url)
            artist_data = response.json()
            return [track["uri"] for track in artist_data["tracks"]]
        except requests.exceptions.HTTPError:
            return []

    def _get_artists_albums(self, artist_id: str) -> typing.List[str]:
        url = f"https://api.spotify.com/v1/artists/{artist_id}/albums"

        try:
            response = self._make_spotify_request("get", url)
            artist_data = response.json()
            return [album["uri"] for album in artist_data["items"]]
        except requests.exceptions.HTTPError:
            return []

    def _get_songs_from_search(
        self, search_response: typing.Dict[str, str]
    ) -> typing.List[str]:
        play_uri = search_response["uri"]
        play_type = search_response["type"]

        songs = []
        if play_type == "albums":
            songs = self._get_tracks_from_album(play_uri.split(":")[-1])

        elif play_type == "tracks":
            songs = [play_uri]

        elif play_type == "artists":
            top_songs = self._get_artists_top_tracks(search_response["id"])
            albums = self._get_artists_albums(search_response["id"])

            songs_on_albums = [
                self._get_tracks_from_album(album.split(":")[-1]) for album in albums
            ]

            songs = [
                *top_songs,
                *[song for album in songs_on_albums for song in album],
            ]

        return songs
