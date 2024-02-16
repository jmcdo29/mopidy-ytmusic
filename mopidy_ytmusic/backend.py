import random
import re
import time

import pykka
import requests
from mopidy import backend
from ytmusicapi import YTMusic

from mopidy_ytmusic import logger

from .library import YTMusicLibraryProvider, title_to_uri
from .playback import YTMusicPlaybackProvider
from .playlist import YTMusicPlaylistsProvider
from .repeating_timer import RepeatingTimer
from .scrobble_fe import YTMusicScrobbleListener


class YTMusicBackend(
    pykka.ThreadingActor, backend.Backend, YTMusicScrobbleListener
):
    def __init__(self, config, audio):
        super().__init__()
        self.config = config
        self.audio = audio
        self.uri_schemes = ["ytmusic"]
        self.auth = False

        self._auto_playlist_refresh_rate = (
            config["ytmusic"]["auto_playlist_refresh"] * 60
        )
        self._auto_playlist_refresh_timer = None

        self._youtube_player_refresh_rate = (
            config["ytmusic"]["youtube_player_refresh"] * 60
        )
        self._youtube_player_refresh_timer = None

        self.playlist_item_limit = config["ytmusic"]["playlist_item_limit"]
        self.subscribed_artist_limit = config["ytmusic"][
            "subscribed_artist_limit"
        ]
        self.history = config["ytmusic"]["enable_history"]
        self.liked_songs = config["ytmusic"]["enable_liked_songs"]
        self.mood_genre = config["ytmusic"]["enable_mood_genre"]
        self.stream_preference = config["ytmusic"]["stream_preference"]
        self.verify_track_url = config["ytmusic"]["verify_track_url"]

        if "oauth_json" in config["ytmusic"]:
            self.api = YTMusic(auth=config["ytmusic"]["oauth_json"])
            self.auth = True
        elif "auth_json" in config["ytmusic"]:
            self.api = YTMusic(config["ytmusic"]["auth_json"])
            self.auth = True
        else:
            self.api = YTMusic()

        self.playback = YTMusicPlaybackProvider(audio=audio, backend=self)
        self.library = YTMusicLibraryProvider(backend=self)
        if self.auth:
            self.playlists = YTMusicPlaylistsProvider(backend=self)

    def on_start(self):
        if self._auto_playlist_refresh_rate:
            self._auto_playlist_refresh_timer = RepeatingTimer(
                self._refresh_auto_playlists, self._auto_playlist_refresh_rate
            )
            self._auto_playlist_refresh_timer.start()

        self._youtube_player_refresh_timer = RepeatingTimer(
            self._refresh_youtube_player, self._youtube_player_refresh_rate
        )
        self._youtube_player_refresh_timer.start()

    def on_stop(self):
        if self._auto_playlist_refresh_timer:
            self._auto_playlist_refresh_timer.cancel()
            self._auto_playlist_refresh_timer = None
        if self._youtube_player_refresh_timer:
            self._youtube_player_refresh_timer.cancel()
            self._youtube_player_refresh_timer = None

    def _refresh_youtube_player(self):
        t0 = time.time()
        url = self._get_youtube_player()
        if url is not None:
            if self.playback.Youtube_Player_URL != url:
                self.playback.update_cipher(playerurl=url)
            t = time.time() - t0
            logger.debug("YTMusic Player URL refreshed in %.2fs", t)

    def _get_youtube_player(self):
        # Refresh our js player URL so YDL can decode the signature correctly.
        try:
            self.api.headers.pop('filepath', None)
            response = requests.get(
                "https://music.youtube.com",
                headers=self.api.headers,
                proxies=self.api.proxies,
            )
            m = re.search(r'jsUrl"\s*:\s*"([^"]+)"', response.text)
            if m:
                url = m.group(1)
                logger.debug("YTMusic updated player URL to %s", url)
                return url
            else:
                logger.error("YTMusic unable to extract player URL.")
                return None
        except Exception:
            logger.exception("YTMusic failed to refresh player URL.")
        return None

    def _refresh_auto_playlists(self):
        t0 = time.time()
        self._get_auto_playlists()
        t = time.time() - t0
        logger.info("YTMusic Auto Playlists refreshed in %.2fs", t)

    def _get_auto_playlists(self):
        try:
            logger.debug("YTMusic loading auto playlists")
            response = self.api.get_home(limit=7)
                # limit needs to be >6 to usually include "Mixed for You"
            browse = parse_auto_playlists(response)
            # Delete empty sections
            empty_sections = set()
            for uri, section in browse.items():
                if len(section) == 0:
                    empty_sections.add(uri)

            for uri in empty_sections:
                browse.pop(uri)
            logger.info(
                "YTMusic loaded %d auto playlists sections", len(browse)
            )
            self.library.ytbrowse = browse
        except Exception:
            logger.exception("YTMusic failed to load auto playlists")
        return None

    def scrobble_track(self, bId):
        # Called through YTMusicScrobbleListener
        # Let YTMusic know we're playing this track so it will be added to our history.
        CPN_ALPHABET = (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
        )
        cpn = "".join(
            (CPN_ALPHABET[random.randint(0, 256) & 63] for _ in range(0, 16))
        )
        player_response = self.api._send_request(
            "player",
            {
                "playbackContext": {
                    "contentPlaybackContext": {
                        "signatureTimestamp": self.playback.signatureTimestamp,
                    },
                },
                "videoId": bId,
                "cpn": cpn,
            },
        )
        params = {
            "cpn": cpn,
            "ver": 2,
            "c": "WEB_REMIX",
        }
        tr = requests.get(
            player_response["playbackTracking"]["videostatsPlaybackUrl"][
                "baseUrl"
            ],
            params=params,
            headers=self.api.headers,
            proxies=self.api.proxies,
        )
        logger.debug("%d code from '%s'", tr.status_code, tr.url)


def parse_auto_playlists(res):
    browse = {}
    for sect in res:
        stitle = sect["title"]
        section_uri = title_to_uri(stitle, 'auto')
        browse[section_uri] = []
        for item in sect["contents"]:
            if item is None: # empty result
                continue
            elif "playlistId" in item: # playlist result
                browse[section_uri].append(
                    {
                        "type": "playlist",
                        "uri": f"ytmusic:playlist:{item['playlistId']}",
                        "name": item["title"]
                    })
            elif "subscribers" in item: # artist result
                browse[section_uri].append(
                    {
                        "type": "artist",
                        "uri": f"ytmusic:artist:{item['browseId']}",
                        "name": item['title'] + " (Artist)"
                    })
            elif "year" in item: # album result
                browse[section_uri].append(
                    {
                        "type": "album",
                        "uri": f"ytmusic:album:{item['browseId']}",
                        "name": f"{item['year']} - {item['title']} (Album)"
                    }
                )
            # ignoring song quick-picks here


    return browse
