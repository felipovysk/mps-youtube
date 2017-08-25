import spotipy
import spotipy.oauth2 as oauth2
import re
import time
import difflib

import pafy

from .. import c, g, screen, __version__, __url__, content, config, util
from . import command
from .songlist import paginatesongs
from .search import generate_search_qs, get_tracks_from_json


def generate_credentials():
    """Generate the token. Please respect these credentials :)"""
    credentials = oauth2.SpotifyClientCredentials(
        client_id='4fe3fecfe5334023a1472516cc99d805',
        client_secret='0f02b7c483c04257984695007a4a8d5c')
    return credentials


def grab_playlist(spotify, playlist):
    if '/' in playlist:
        if playlist.endswith('/'):
            playlist = playlist[:-1]
        splits = playlist.split('/')
    else:
        splits = playlist.split(':')

    username = splits[-3]
    playlist_id = splits[-1]
    playlists = spotify.user_playlists(username)

    while True:
        for playlist in playlists['items']:
            if not playlist['name'] == None:
                if playlist['id'] == playlist_id:
                    playlists['next'] = None
                    break
        if playlists['next']:
            playlists = spotify.next(playlists)
        else:
            break

    if playlists['total'] == 0:
        return

    owner_id = playlist['owner']['id']
    playlist_id = playlist['id']
    results = spotify.user_playlist(owner_id, playlist_id, fields='tracks,next')

    all_tracks = []
    tracks = results['tracks']
    while True:
        for item in tracks['items']:
            track = item['track']
            try:
                #util.xprint(track['external_urls']['spotify'])
                all_tracks.append(track)
            except KeyError:
                pass
        # 1 page = 50 results
        # check if there are more pages
        if tracks['next']:
            tracks = spotify.next(tracks)
        else:
            break

    return (playlist, all_tracks)


def show_message(message, col=c.r, update=False):
    """ Show message using col, update screen if required. """
    g.content = content.generate_songlist_display()
    g.message = col + message + c.w

    if update:
        screen.update()


def _best_song_match(songs, title, duration, titleweight, durationweight):
    """ Select best matching song based on title, length.

    Score from 0 to 1 where 1 is best. titleweight and durationweight
    parameters added to enable function usage when duration can't be guessed

    """
    # pylint: disable=R0914
    seqmatch = difflib.SequenceMatcher

    def variance(a, b):
        """ Return difference ratio. """
        return float(abs(a - b)) / max(a, b)

    candidates = []

    ignore = "music video lyrics new lyrics video audio".split()
    extra = "official original vevo".split()

    for song in songs:
        dur, tit = int(song.length), song.title
        util.dbg("Title: %s, Duration: %s", tit, dur)

        for word in extra:
            if word in tit.lower() and word not in title.lower():
                pattern = re.compile(word, re.I)
                tit = pattern.sub("", tit)

        for word in ignore:
            if word in tit.lower() and word not in title.lower():
                pattern = re.compile(word, re.I)
                tit = pattern.sub("", tit)

        replacechars = re.compile(r"[\]\[\)\(\-]")
        tit = replacechars.sub(" ", tit)
        multiple_spaces = re.compile(r"(\s)(\s*)")
        tit = multiple_spaces.sub(r"\1", tit)

        title_score = seqmatch(None, title.lower(), tit.lower()).ratio()
        duration_score = 1 - variance(duration, dur)
        util.dbg("Title score: %s, Duration score: %s", title_score,
                 duration_score)

        # apply weightings
        score = duration_score * durationweight + title_score * titleweight
        candidates.append((score, song))

    best_score, best_song = max(candidates, key=lambda x: x[0])
    percent_score = int(100 * best_score)
    return best_song, percent_score


def _match_tracks(tracks):
    """ Match list of tracks by performing multiple searches. """
    # pylint: disable=R0914

    def dtime(x):
        """ Format time to M:S. """
        return time.strftime('%M:%S', time.gmtime(int(x)))

    # do matching
    for track in tracks:
        ttitle = track['name']
        artist = track['artists'][0]['name']
        length = track['duration_ms']/1000
        util.xprint("Search :  %s%s - %s%s - %s" % (c.y, artist, ttitle, c.w,
                                                    dtime(length)))
        q = "%s %s" % (artist, ttitle)
        w = q = ttitle if artist == "Various Artists" else q
        query = generate_search_qs(w, 0)
        util.dbg(query)

        # perform fetch
        wdata = pafy.call_gdata('search', query)
        results = get_tracks_from_json(wdata)

        if not results:
            util.xprint(c.r + "Nothing matched :(\n" + c.w)
            continue

        s, score = _best_song_match(
            results, artist + " " + ttitle, length, .5, .5)
        cc = c.g if score > 85 else c.y
        cc = c.r if score < 75 else cc
        util.xprint("Matched:  %s%s%s - %s \n[%sMatch confidence: "
                    "%s%s]\n" % (c.y, s.title, c.w, util.fmt_time(s.length),
                                 cc, score, c.w))
        yield s


@command(r'splaylist\s(.*[-_a-zA-Z0-9].*)')
def search_playlist(term):
    """Search for Spotify playlist. """
    # pylint: disable=R0914,R0912
    if not term:
        show_message("Enter playlist url:", c.g, update=True)
        term = input("> ")

        if not term or len(term) < 2:
            g.message = c.r + "Not enough input!" + c.w
            g.content = content.generate_songlist_display()
            return

    credentials = generate_credentials()
    token = credentials.get_access_token()
    spotify = spotipy.Spotify(auth=token)

    playlist, tracks = grab_playlist(spotify, 'https://open.spotify.com/user/1110716798/playlist/2NwWoITrXtgxDBAvzGIz52')

    if not tracks:
        show_message("Playlist '%s' not found!" % term)
        return

    out = "'%s' by %s%s%s\n\n" % (playlist['name'],
                                  c.g, playlist['owner']['id'], c.w)

    if not playlist['tracks']['total']:
        show_message("Playlist '%s' by '%s' has 0 tracks!" % (playlist['name'], playlist['owner']['id']))
        return

    msg = "%s%s%s by %s%s%s\n\n" % (c.g, playlist['name'], c.w, c.g, playlist['owner']['id'], c.w)
    msg += "Enter to begin matching or [q] to abort"
    g.message = msg
    g.content = "Tracks:\n"
    for n, track in enumerate(tracks, 1):
        trackname = track['artists'][0]['name'] + ' - ' + track['name']
        g.content += "%02s  %s" % (n, trackname)
        g.content += "\n"

    screen.update()
    entry = input("Continue? [Enter] > ")

    if entry == "":
        pass

    else:
        show_message("Album search abandoned!")
        return

    songs = []
    screen.clear()
    itt = _match_tracks(tracks)

    stash = config.SEARCH_MUSIC.get, config.ORDER.get
    config.SEARCH_MUSIC.value = True
    config.ORDER.value = "relevance"

    try:
        songs.extend(itt)

    except KeyboardInterrupt:
        util.xprint("%sHalted!%s" % (c.r, c.w))

    finally:
        config.SEARCH_MUSIC.value, config.ORDER.value = stash

    if songs:
        util.xprint("\n%s / %s songs matched" % (len(songs), len(mb_tracks)))
        input("Press Enter to continue")

    msg = "Contents of album %s%s - %s%s %s(%d/%d)%s:" % (
        c.y, artist, title, c.w, c.b, len(songs), len(mb_tracks), c.w)
    failmsg = "Found no album tracks for %s%s%s" % (c.y, title, c.w)

    paginatesongs(songs, msg=msg, failmsg=failmsg)
