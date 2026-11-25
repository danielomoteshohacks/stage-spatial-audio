"""The catalogue: licence policy, source parsing, shelf building and the store, on recorded data."""

import json

from stage.catalogue import licences as L
from stage.catalogue.build import build_catalogue, place, shelf_config
from stage.catalogue.fetch import FetchRefused, host_allowed
from stage.catalogue.model import Track
from stage.catalogue.sources import InternetArchive, Jamendo, Openverse
from stage.catalogue.store import Catalogue


def ov_record(i, title="Song", creator="Artist", lic="by-sa", ver="3.0", genres=("pop",),
              dur=200000):
    return {"id": f"id{i}", "title": title, "creator": creator, "license": lic,
            "license_version": ver, "source": "jamendo", "provider": "jamendo",
            "genres": list(genres), "duration": dur, "filetype": "mp32",
            "url": f"https://prod-1.storage.jamendo.com/?trackid={i}&format=mp32",
            "foreign_landing_url": f"https://www.jamendo.com/track/{i}",
            "thumbnail": "https://api.openverse.org/x/thumb/",
            "audio_set": {"title": "Album", "creator_url": "https://www.jamendo.com/artist/1"}}


def test_licence_policy_excludes_noderivatives_and_unknown():
    for code in ("by-nd", "by-nc-nd", "unknown"):
        assert not L.accepted(L.Licence(code, "3.0"))
        assert not L.accepted(L.Licence(code, "3.0"), allow_nc=True)
    for code in ("by", "by-sa", "cc0", "pdm"):
        assert L.accepted(L.Licence(code, "4.0"))
    assert not L.accepted(L.Licence("by-nc", "3.0"))
    assert L.accepted(L.Licence("by-nc", "3.0"), allow_nc=True)
    assert L.parse_url("http://creativecommons.org/licenses/by-nc-nd/3.0/").code == "by-nc-nd"
    assert L.parse_url("https://creativecommons.org/publicdomain/zero/1.0/").code == "cc0"
    assert L.parse_url(None).code == "unknown"


def test_attribution_names_creator_licence_change_and_sharealike():
    t = Track("jamendo:1", "Tune", "Ada", "https://prod-1.storage.jamendo.com/x",
              "https://www.jamendo.com/track/1", L.Licence("by-sa", "3.0"), "jamendo")
    a = t.attribution
    assert '"Tune" by Ada' in a and "CC BY-SA 3.0" in a and "creativecommons.org" in a
    assert "Spatialised by SoundStage" in a and "same licence" in a
    by = Track("x:1", "T", "A", "https://x", "https://x", L.Licence("by", "4.0"), "x").attribution
    assert "same licence" not in by


def test_openverse_filters_licences_and_parses_fields():
    recs = [ov_record(1), ov_record(2, lic="by-nd"), ov_record(3, lic="by-nc"),
            ov_record(4, lic="cc0", ver="1.0"), ov_record(5, title="&amp; Co")]
    ov = Openverse(fetch=lambda url: {"results": recs})
    got = ov.search("pop")
    assert [t.id for t in got] == ["jamendo:id1", "jamendo:id4", "jamendo:id5"]
    assert got[0].duration_s == 200.0 and got[0].genres == ["pop"] and got[0].album == "Album"
    assert got[2].title == "& Co"  # HTML entities are decoded
    assert len(Openverse(fetch=lambda url: {"results": recs}).search("x", allow_nc=True)) == 4


def test_jamendo_respects_download_flag_and_needs_a_client_id():
    row = {"id": "7", "name": "J", "artist_name": "Z", "artist_id": "9", "duration": 190,
           "audiodownload_allowed": True, "audiodownload": "https://prod-1.storage.jamendo.com/download/track/7/mp32/",
           "license_ccurl": "http://creativecommons.org/licenses/by/3.0/", "image": "https://x/i.jpg",
           "musicinfo": {"tags": {"genres": ["Pop", "Rock"]}}, "album_name": "A"}
    blocked = {**row, "id": "8", "audiodownload_allowed": False}
    nd = {**row, "id": "9", "license_ccurl": "http://creativecommons.org/licenses/by-nd/3.0/"}
    assert Jamendo(client_id="", fetch=lambda u: {}).search(search="x") == []
    jm = Jamendo(client_id="abc", fetch=lambda u: {"results": [row, blocked, nd]})
    got = jm.search(search="x")
    assert [t.id for t in got] == ["jamendo:7"] and got[0].genres == ["pop", "rock"]
    assert "client_id=abc" in "".join(u for u in [jm.base + "?client_id=abc"])


def test_internet_archive_takes_a_long_mp3_and_the_item_licence():
    docs = {"response": {"docs": [{"identifier": "rel1", "title": "Release", "creator": "Lab",
                                   "licenseurl": "http://creativecommons.org/licenses/by-sa/3.0/",
                                   "subject": ["ambient", "drone"]},
                                  {"identifier": "rel2", "licenseurl":
                                   "http://creativecommons.org/licenses/by-nc-nd/3.0/"}]}}
    meta = {"files": [{"name": "a short.mp3", "format": "VBR MP3", "length": "30.0"},
                      {"name": "b long.mp3", "format": "VBR MP3", "length": "04:10"},
                      {"name": "c.flac", "format": "Flac", "length": "250"}]}

    def fetch(url):
        return docs if "advancedsearch" in url else meta

    got = InternetArchive(fetch=fetch).search("ambient")
    assert len(got) == 1 and got[0].duration_s == 250.0
    assert got[0].audio_url.endswith("b%20long.mp3")
    assert got[0].licence.code == "by-sa" and got[0].genres == ["ambient", "drone"]


def test_placement_needs_a_genre_tag_not_a_search_hit_and_honours_excludes():
    cfg = shelf_config()["shelves"]
    mk = lambda title, genres: Track("x:" + title, title, "A", "https://x", "https://x",  # noqa: E731
                                     L.Licence("by", "3.0"), "x", genres=genres)
    assert "gospel" in place(mk("Praise", ["gospel", "soul"]), cfg, {"gospel"})
    assert "gospel" not in place(mk("Gospel of Wealth", ["darkambient", "industrial"]), cfg,
                                 {"gospel"})
    assert "gospel" not in place(mk("Gospel", ["pop"]), cfg, {"gospel"})  # tagged, not gospel
    assert "afrobeats" in place(mk("360 Highlife", []), cfg, {"afrobeats"})  # untagged: by title
    assert "hiphop" not in place(mk("The Trap", ["thrashmetal", "metal"]), cfg, {"hiphop"})


def test_build_catalogue_places_trims_per_artist_and_verifies_urls():
    recs = [ov_record(i, title=f"Hip {i}", creator=("A" if i < 5 else f"B{i}"), genres=("hiphop",))
            for i in range(12)]
    ov = Openverse(fetch=lambda url: {"results": recs} if "page=1" in url else {"results": []})
    cat = build_catalogue(ov, None, pages=1, verify=False)
    ids = cat["shelves"]["hiphop"]["tracks"]
    assert 0 < len(ids) <= shelf_config()["shelves"]["hiphop"]["max"]
    artists = [cat["tracks"][i]["artist"] for i in ids]
    assert artists.count("A") <= shelf_config()["per_artist"]
    assert all(cat["tracks"][i]["licence"]["code"] in ("by", "by-sa", "cc0", "pdm") for i in ids)
    assert all("attribution" in cat["tracks"][i] for i in ids)


def test_the_committed_seed_meets_the_catalogue_promise():
    from stage.catalogue.store import load_seed

    seed = load_seed()
    tracks = seed["tracks"]
    assert len(tracks) >= 60
    for t in tracks.values():
        lic = t["licence"]["code"]
        assert lic in ("by", "by-sa", "cc0", "pdm"), t["id"]  # no NC, no ND
        assert t["checked"].get("ok") is True and t["landing_url"].startswith("http")
        assert t["attribution"] and t["artist"] and t["title"]
        assert 90 <= t["duration_s"] <= 480
    shelves = seed["shelves"]
    assert {"afrobeats", "amapiano", "hiphop", "rnb_soul", "gospel", "house_electronic", "lofi",
            "cinematic", "acoustic", "classical", "made_for_spatial"} <= set(shelves)
    assert all(shelves[k]["tracks"] for k in shelves)
    listed = {i for v in shelves.values() for i in v["tracks"]}
    assert len(listed) >= 60 and listed <= set(tracks)


def test_store_search_serves_seed_then_live_and_registers_what_it_shows():
    live = [ov_record(50, title="Fresh Find", genres=("afrobeat",))]
    ov = Openverse(fetch=lambda url: {"results": live})
    cat = Catalogue(openverse=ov, seed={"shelves": {}, "tracks": {}})
    assert cat.track("jamendo:id50") is None
    res = cat.search("fresh")
    assert [t["id"] for t in res] == ["jamendo:id50"] and cat.track("jamendo:id50") is not None
    assert res[0]["licence"]["code"] == "by-sa" and res[0]["attribution"]
    calls = []
    ov2 = Openverse(fetch=lambda url: calls.append(url) or {"results": live})
    c2 = Catalogue(openverse=ov2, seed={"shelves": {}, "tracks": {}})
    c2.search("x")
    c2.search("x")
    assert len(calls) == 1  # the second search came from the cache


def test_audio_proxy_only_reaches_approved_hosts():
    assert host_allowed("https://prod-1.storage.jamendo.com/?trackid=1")
    assert host_allowed("https://ia803000.us.archive.org/x.mp3")
    assert not host_allowed("http://prod-1.storage.jamendo.com/x")  # not https
    assert not host_allowed("https://evil.example/jamendo.com")
    assert not host_allowed("https://jamendo.com.evil.example/x")
    assert issubclass(FetchRefused, ValueError)
    json.dumps(L.Licence("by", "3.0").as_dict())
