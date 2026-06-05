import base64
import datetime
import http.server
import os
import socketserver
import threading
import typing
import urllib.parse
import webbrowser

import requests

from helpers.audio import Audio
from helpers.cache import Cache
from helpers.decorators import retry_on_unauthorized
from helpers.registry import method_job, register_service
from helpers.requirements import Requirement

auth_code = None


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

            # Signal the server to shut down
            threading.Thread(target=self.server.shutdown).start()
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
            "Create an app at developer.spotify.com/dashboard, add SPOTIFY_CLIENT_ID "
            "and SPOTIFY_CLIENT_SECRET to .env, set Redirect URI to http://127.0.0.1:8888/callback"
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
    SCOPE = "user-read-playback-state user-modify-playback-state playlist-read-private playlist-read-collaborative user-library-modify user-library-read"

    def __init__(self):
        self.albums = {}

        self.client_id = os.getenv(self.ENV_SPOTIFY_CLIENT_ID)
        self.client_secret = os.getenv(self.ENV_SPOTIFY_CLIENT_SECRET)

        self.access_token, self.refresh_token = self._get_tokens_from_cache()

        if not self.access_token or not self.refresh_token:
            self.auth_code = self._get_auth_code()
            if not self.auth_code:
                raise Exception("Failed to get authorization code")

            self.access_token, self.refresh_token = self._get_tokens()
            if not self.access_token or not self.refresh_token:
                raise Exception("Failed to get access token and refresh token")

        self.device_id = self._get_active_devices()
        if not self.device_id:
            raise Exception("No active Spotify device found")

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def play_songs(self, title: str, artist: str, content_type: str = "") -> typing.Optional[str]:
        """
        [SPOTIFY SERVICE METHOD] Searches and plays music on Spotify by title and/or artist.
        This service method integrates with Spotify API to find and start playbook of songs,
        albums, or artist catalogs based on user search criteria.

        Use this method when the user wants to:
        - Play specific songs or albums on Spotify
        - Start music playback with search terms
        - Listen to music by particular artists
        - Stream audio content through Spotify

        Keywords: play, song, track, music, spotify, search, listen, stream, music playback,
                 start music, play spotify, listen to, put on music

        Args:
            title (str): Title of the song or an album to play, or name of the artist if no album/song is specified. (required)
            artist (str): Artist of the song to play, if not specified by user then set to empty string (""). (required)
            content_type (str): Type of content to play - "track" for a single song, "album" for a full album,
                               "artist" for all music by an artist. Leave empty to use first found result.
                               Infer from user intent: "play song X" → "track", "play album X" → "album",
                               "play all music by X" / "play everything by X" → "artist"

        Returns:
            str: Success message with track/album details or error message if not found.
        """

        if not title and not artist:
            self.start_playback()
            return

        search_response = self._search(query=title, artist=artist, content_type=content_type)

        if not search_response:
            self._handle_search_not_found(title, artist)
            return

        self._announce_action(
            f"Playing {search_response['name']} by {search_response['artist']}"
        )

        songs = self._get_songs_from_search(search_response)
        url = self._build_url_with_device("https://api.spotify.com/v1/me/player/play")

        data = {"uris": songs}

        self.toggle_shuffle(state=False)
        self._make_spotify_request("put", url, json=data)

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def add_to_queue(self, title: str, artist: str) -> None:
        """
        [SPOTIFY SERVICE METHOD] Adds songs or albums to the Spotify playback queue for later listening.
        This service method searches for music content and adds it to the current playback queue
        without interrupting the currently playing track.

        Use this method when the user wants to:
        - Add songs to play later
        - Queue up music for continuous listening
        - Build a listening sequence
        - Add tracks without stopping current playback

        Keywords: add, queue, song, track, music, spotify, add to queue, queue up,
                 add song, queue music, add track, queue this, add to playlist

        Args:
            title (str): Title of the song or an album to add, or name of the artist if no album/song is specified. (required)
            artist (str): Artist of the song to add, if not specified by user then set to empty string (""). (required)

        Returns:
            None: Specified music will be added to the Spotify queue.
        """

        search_response = self._search(query=title, artist=artist)

        if not search_response:
            self._handle_search_not_found(title, artist)
            return

        self._announce_action(
            f"Adding {search_response['name']} by {search_response['artist']} to the queue"
        )

        base_url = "https://api.spotify.com/v1/me/player/queue"
        url = self._build_url_with_device(base_url)

        songs = self._get_songs_from_search(search_response)

        for song in songs:
            separator = "&" if self.device_id else "?"
            request_url = f"{url}{separator}uri={song}"
            self._make_spotify_request("post", request_url)

    @method_job
    def toggle_playback(self) -> None:
        """
        [SPOTIFY SERVICE METHOD] Switches between play and pause states for current Spotify playback.
        This service method checks the current playback state and toggles it - pausing if playing,
        or resuming if paused. Provides smart playback control based on current state.

        Use this method when the user wants to:
        - Switch between play and pause
        - Toggle current music playback
        - Smart play/pause control
        - Resume or stop current track

        Keywords: play/pause, toggle, switch, playback, music, spotify, resume/stop,
                 pause/play, toggle music, switch playback, music control

        Args:
            None

        Returns:
            None: Playback state will be toggled automatically.
        """

        is_playing = self._is_playback_playing()

        if is_playing:
            self.stop_playback()

        else:
            self.start_playback()

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def start_playback(self) -> None:
        """
        [SPOTIFY SERVICE METHOD] Resumes or starts Spotify music playback from current position.
        This service method sends play command to Spotify API to begin or continue playback
        of the current track or playlist from where it was last stopped.

        Use this method when the user wants to:
        - Start playing music on Spotify
        - Resume paused playback
        - Continue current track or playlist
        - Begin music streaming

        Keywords: play, start, resume, begin, music, spotify, playback, continue,
                 start music, resume music, play spotify, continue playback

        Args:
            None

        Returns:
            None: Spotify playback will start/resume.
        """

        url = self._build_url_with_device("https://api.spotify.com/v1/me/player/play")
        self._make_spotify_request("put", url)
        print("Playback resumed")

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def stop_playback(self) -> None:
        """
        [SPOTIFY SERVICE METHOD] Pauses current Spotify music playback at current position.
        This service method sends pause command to Spotify API to temporarily stop playback
        while maintaining the current position for later resumption.

        Use this method when the user wants to:
        - Pause current music playback
        - Stop Spotify temporarily
        - Silence the music momentarily
        - Halt current track playback

        Keywords: pause, stop, halt, silence, quiet, mute, spotify, music,
                 pause music, stop spotify, halt playback, pause song

        Args:
            None

        Returns:
            None: Spotify playback will be paused.
        """

        url = self._build_url_with_device("https://api.spotify.com/v1/me/player/pause")
        self._make_spotify_request("put", url)
        print("Playback paused")

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def skip_song(self) -> None:
        """
        [SPOTIFY SERVICE METHOD] Advances to the next track in the current Spotify playlist or queue.
        This service method skips the currently playing song and moves forward to the next
        available track in the playback sequence.

        Use this method when the user wants to:
        - Skip the current song
        - Move to the next track
        - Advance through playlist
        - Change to a different song

        Keywords: next, skip, forward, another, song, track, spotify, advance,
                 next song, skip song, next track, forward song, skip this

        Args:
            None

        Returns:
            None: Playback will advance to the next track.
        """

        url = self._build_url_with_device("https://api.spotify.com/v1/me/player/next")
        self._make_spotify_request("post", url)
        print("Skipped a song")

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def previous_song(self) -> None:
        """
        Skips to the previous song in Spotify music playback.

        Keywords: previous, back, last, prior, before, rewind, spotify, song, track

        Args:
            None

        Returns:
            None
        """

        url = self._build_url_with_device(
            "https://api.spotify.com/v1/me/player/previous"
        )
        self._make_spotify_request("post", url)
        print("Skipped to the previous song")

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def volume_up(self) -> None:
        """
        [SPOTIFY SERVICE METHOD] Increases Spotify playback volume by 10% increments.
        This service method adjusts the volume control through Spotify API, making the music
        louder while ensuring it doesn't exceed maximum volume limits.

        Use this method when the user wants to:
        - Make Spotify music louder
        - Increase audio volume
        - Turn up the sound
        - Boost music volume

        Keywords: louder, increase, volume up, turn up, higher, spotify, sound,
                 increase volume, make louder, turn up volume, boost sound

        Args:
            None

        Returns:
            None: Spotify volume will be increased by 10%.
        """
        playback_state = self._get_playback_state()
        if not playback_state:
            return

        current_volume = playback_state.get("device", {}).get("volume_percent", 50)
        new_volume = min(current_volume + 10, 100)

        self.set_volume(volume=new_volume)

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def volume_down(self) -> None:
        """
        Decreases Spotify playback volume by 10%.

        Keywords: quieter, decrease, volume down, turn down, lower, spotify, sound

        Args:
            None

        Returns:
            None
        """
        playback_state = self._get_playback_state()
        if not playback_state:
            return

        current_volume = playback_state.get("device", {}).get("volume_percent", 50)
        new_volume = max(current_volume - 10, 0)

        self.set_volume(volume=new_volume)

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def max_volume(self) -> None:
        """
        Sets Spotify playback volume to maximum (100%).

        Keywords: maximum, max volume, full volume, loudest, spotify, sound

        Args:
            None

        Returns:
            None
        """

        self.set_volume(volume=100)

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def set_volume(self, volume: int) -> None:
        """
        Sets Spotify playback volume to a specific level.

        Keywords: set volume, adjust volume, change volume, spotify, sound

        Args:
            volume (int): Volume level between 0 and 100. (required)

        Returns:
            None
        """

        try:
            volume = int(volume)
        except ValueError:
            return

        if not 0 <= volume <= 100:
            return

        base_url = (
            f"https://api.spotify.com/v1/me/player/volume?volume_percent={volume}"
        )
        url = self._build_url_with_device(base_url, "&")

        self._make_spotify_request("put", url)
        print(f"Volume set to {volume}%")

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def get_current_track(self) -> str:
        """
        [SPOTIFY SERVICE METHOD] Announces the currently playing track and artist on Spotify.

        Use this method when the user wants to:
        - Know what song is currently playing
        - Find out the artist of the current track
        - Check what's on

        Keywords: what's playing, now playing, current song, current track, what song,
                 playing now, what music, song name, track name, who's playing

        Args:
            None

        Returns:
            str: Track and artist name, or a message if nothing is playing.
        """
        state = self._get_playback_state()
        if not state or "item" not in state or state.get("item") is None:
            result = "Nothing is currently playing on Spotify."
        else:
            item = state["item"]
            name = item.get("name", "Unknown")
            artists = ", ".join(a["name"] for a in item.get("artists", []))
            result = f"Now playing: {name}" + (f" by {artists}" if artists else "") + "."

        self._announce_action(result)
        return result

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def like_current_track(self) -> typing.Optional[str]:
        """
        [SPOTIFY SERVICE METHOD] Saves the currently playing track to the user's Liked Songs.

        Use this method when the user wants to:
        - Like the current song
        - Save the current track
        - Add the current song to liked songs

        Keywords: like, love, save, heart, favorite, current song, this song, liked songs

        Args:
            None

        Returns:
            str: Confirmation message or error if nothing is playing.
        """
        track_id = self._get_current_track_id()
        if not track_id:
            msg = "Nothing is currently playing"
            self._announce_action(msg)
            return msg

        self._make_spotify_request(
            "put",
            f"https://api.spotify.com/v1/me/tracks?ids={track_id}",
        )
        state = self._get_playback_state()
        name = state["item"]["name"] if state and state.get("item") else "Track"
        msg = f"Liked {name}"
        self._announce_action(msg)
        return msg

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def unlike_current_track(self) -> typing.Optional[str]:
        """
        [SPOTIFY SERVICE METHOD] Removes the currently playing track from the user's Liked Songs.

        Use this method when the user wants to:
        - Unlike the current song
        - Remove the current track from liked songs
        - Dislike this song

        Keywords: unlike, dislike, remove, unsave, unheart, current song, this song, liked songs

        Args:
            None

        Returns:
            str: Confirmation message or error if nothing is playing.
        """
        track_id = self._get_current_track_id()
        if not track_id:
            msg = "Nothing is currently playing"
            self._announce_action(msg)
            return msg

        self._make_spotify_request(
            "delete",
            f"https://api.spotify.com/v1/me/tracks?ids={track_id}",
        )
        state = self._get_playback_state()
        name = state["item"]["name"] if state and state.get("item") else "Track"
        msg = f"Removed {name} from liked songs"
        self._announce_action(msg)
        return msg

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def toggle_like_current_track(self) -> typing.Optional[str]:
        """
        [SPOTIFY SERVICE METHOD] Toggles like/unlike on the currently playing track.

        Use this method when the user wants to:
        - Toggle like on the current song
        - Switch like state of the current track

        Keywords: toggle like, toggle heart, like toggle, current song

        Args:
            None

        Returns:
            str: Confirmation of new like state.
        """
        track_id = self._get_current_track_id()
        if not track_id:
            msg = "Nothing is currently playing"
            self._announce_action(msg)
            return msg

        response = self._make_spotify_request(
            "get",
            f"https://api.spotify.com/v1/me/tracks/contains?ids={track_id}",
        )
        is_liked = response.json()[0]

        if is_liked:
            return self.unlike_current_track()
        else:
            return self.like_current_track()

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def get_playlists(self) -> typing.List[typing.Dict[str, str]]:
        """
        [SPOTIFY SERVICE METHOD] Lists all playlists owned or followed by the current user.

        Use this method when the user wants to:
        - See their playlists
        - Browse available playlists
        - List Spotify playlists

        Keywords: list playlists, show playlists, my playlists, what playlists, browse playlists

        Args:
            None

        Returns:
            list: Playlist dicts with 'name', 'id', and 'uri'.
        """
        playlists = self._get_user_playlists()
        names = ", ".join(p["name"] for p in playlists) if playlists else "No playlists found"
        self._announce_action(names)
        return playlists

    @retry_on_unauthorized("_refresh_access_token")
    @method_job
    def play_playlist(self, name: str) -> typing.Optional[str]:
        """
        [SPOTIFY SERVICE METHOD] Finds a user playlist by name and starts playback.

        Use this method when the user wants to:
        - Play a specific playlist by name
        - Start a named playlist
        - Listen to one of their playlists

        Keywords: play playlist, start playlist, listen to playlist, put on playlist

        Args:
            name (str): Full or partial name of the playlist to play. (required)

        Returns:
            str: Success or error message.
        """
        playlists = self._get_user_playlists()
        name_lower = name.lower()

        match = next(
            (p for p in playlists if name_lower in p["name"].lower()),
            None,
        )

        if not match:
            msg = f"Playlist '{name}' not found"
            self._announce_action(msg)
            return msg

        url = self._build_url_with_device("https://api.spotify.com/v1/me/player/play")
        self._make_spotify_request("put", url, json={"context_uri": match["uri"]})
        msg = f"Playing playlist {match['name']}"
        self._announce_action(msg)
        return msg

    @retry_on_unauthorized("_refresh_access_token")
    def toggle_shuffle(self, **kwargs) -> None:
        """
        Toggles shuffle mode on or off for Spotify playback.

        Keywords: shuffle, random, mix, spotify, playback

        Args:
            None

        Returns:
            None
        """

        state = kwargs.get("state", None)
        if state is None:
            playback_state = self._get_playback_state()
            if not playback_state:
                return
            state = not playback_state.get("shuffle_state", False)

        base_url = (
            f"https://api.spotify.com/v1/me/player/shuffle?state={str(state).lower()}"
        )
        url = self._build_url_with_device(base_url, "&")

        self._make_spotify_request("put", url)

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
        if self.device_id:
            return f"{base_url}{separator}device_id={self.device_id}"
        return base_url

    def _make_spotify_request(
        self, method: str, url: str, **kwargs
    ) -> requests.Response:
        """Make a Spotify API request with standard headers and error handling"""
        headers = kwargs.pop("headers", self._get_auth_headers())
        response = getattr(requests, method.lower())(url, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def _handle_search_not_found(self, title: str, artist: str = "") -> None:
        """Handle case when search returns no results"""
        text = f"Didn't find {title}"
        if artist:
            text += f" by {artist}"

        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech(text)
        else:
            print(text)

    def _announce_action(self, message: str) -> None:
        """Announce an action via audio or print"""
        audio = Cache.get_audio()
        if audio:
            Audio.text_to_speech(message)
        else:
            print(message)

    def _is_playback_playing(self):
        playback_state = self._get_playback_state()

        if playback_state and "is_playing" in playback_state:
            return playback_state["is_playing"]

        return False

    def _get_playback_state(self) -> typing.Optional[typing.Dict[str, typing.Any]]:
        try:
            response = self._make_spotify_request(
                "get", "https://api.spotify.com/v1/me/player"
            )
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 204:
                return {"error": "No active device found"}
            raise

    @retry_on_unauthorized("_refresh_access_token")
    def _get_active_devices(self) -> typing.Optional[str]:
        response = self._make_spotify_request(
            "get", "https://api.spotify.com/v1/me/player/devices"
        )
        devices = response.json().get("devices", [])

        if not devices:
            return None

        # Find active device or use first available
        active_device = next(
            (device for device in devices if device["is_active"]), devices[0]
        )
        return active_device.get("id")

    def _refresh_access_token(self, refresh_token):
        headers = {
            "Authorization": f"Basic {self._get_basic_auth_header()}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

        response = requests.post(
            "https://accounts.spotify.com/api/token", headers=headers, data=data
        )

        if response.status_code == 200:
            token_info = response.json()
            self.access_token = token_info["access_token"]
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

    def _get_auth_code(self):
        auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "redirect_uri": self.REDIRECT_URI,
                "scope": self.SCOPE,
                "show_dialog": "true",
            }
        )

        print(f"Opening browser for authorization: {auth_url}")
        webbrowser.open(auth_url)

        httpd = socketserver.TCPServer(("", self.PORT), AuthHandler)
        print(f"Waiting for authorization at http://localhost:{self.PORT}")
        httpd.serve_forever()

        if auth_code:
            return auth_code

        else:
            return None

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

        response = requests.post(
            "https://accounts.spotify.com/api/token", headers=headers, data=data
        )

        if response.status_code == 200:
            token_info = response.json()
            self.access_token = token_info["access_token"]
            self.refresh_token = token_info["refresh_token"]
            self._save_tokens(self.access_token, self.refresh_token)
            return self.access_token, self.refresh_token
        else:
            self.access_token = None
            self.refresh_token = None
            return None, None

    def _save_tokens(self, access_token, refresh_token):
        expiration_date = datetime.datetime.now() + datetime.timedelta(seconds=3600)
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
