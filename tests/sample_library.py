from pathlib import Path

from overcast_to_sqlite.datastore import Datastore

HARD_FORK_XML = "https://feeds.example.com/hardfork.xml"
OLD_SHOW_XML = "https://feeds.example.com/old.xml"
EP_AGENTS = "https://cdn.example.com/hf/ep101.mp3"
EP_CRYPTO = "https://cdn.example.com/hf/ep102.mp3"
EP_UNHEARD = "https://cdn.example.com/hf/ep103.mp3"
EP_NOT_EXTENDED = "https://cdn.example.com/hf/ep104.mp3"
EP_FEED_ONLY = "https://cdn.example.com/hf/ep105.mp3"
EP_OLD = "https://cdn.example.com/old/ep201.mp3"
TRANSCRIPT_URL = "https://cdn.example.com/hf/ep101.vtt"


def _feed(overcast_id: int, title: str, xml_url: str, **extra: object) -> dict:
    return {
        "overcastId": overcast_id,
        "title": title,
        "xmlUrl": xml_url,
        "htmlUrl": None,
        "subscribed": True,
        "notifications": False,
        "overcastAddedDate": "2024-01-02T00:00:00-05:00",
        **extra,
    }


def _episode(overcast_id: int, feed_id: int, title: str, url: str, **extra) -> dict:
    return {
        "overcastId": overcast_id,
        "feedId": feed_id,
        "title": title,
        "url": f"https://example.com/{overcast_id}",
        "overcastUrl": f"https://overcast.fm/+{overcast_id}",
        "enclosureUrl": url,
        "played": False,
        "progress": None,
        "userDeleted": False,
        "userRecommendedDate": None,
        **extra,
    }


def populate(db_path: Path) -> None:
    store = Datastore(str(db_path))
    store.save_feed_and_episodes(
        _feed(1, "Hard Fork", HARD_FORK_XML),
        [
            _episode(
                101,
                1,
                "AI Agents Everywhere",
                EP_AGENTS,
                played=True,
                userUpdatedDate="2026-09-01T10:00:00-04:00",
                userRecommendedDate="2026-09-01T11:00:00-04:00",
                pubDate="2026-08-30T08:00:00+00:00",
            ),
            _episode(
                102,
                1,
                "Crypto Winter Returns",
                EP_CRYPTO,
                progress=1_200,
                userUpdatedDate="2026-09-05T09:00:00+00:00",
            ),
            _episode(
                103,
                1,
                "Unheard Episode",
                EP_UNHEARD,
                progress=100,
                userUpdatedDate="2026-09-06T09:00:00+00:00",
            ),
            _episode(
                104,
                1,
                "Not In Feed Yet",
                EP_NOT_EXTENDED,
                played=True,
                userUpdatedDate="2026-09-07T09:00:00+00:00",
            ),
        ],
    )
    store.save_feed_and_episodes(
        _feed(
            2,
            "Old Show",
            OLD_SHOW_XML,
            subscribed=False,
            dateRemoveDetected="2025-06-01T00:00:00+00:00",
        ),
        [
            _episode(
                201,
                2,
                "Old Times",
                EP_OLD,
                played=True,
                userUpdatedDate="2025-01-01T09:00:00+00:00",
            ),
        ],
    )
    store.save_extended_feed_and_episodes(
        {
            "xmlUrl": HARD_FORK_XML,
            "title": "Hard Fork",
            "description": "<p>A show about <b>tech</b> &amp; the future.</p>",
            "lastUpdated": "2026-09-08T00:00:00+00:00",
            "link": "https://hardfork.example.com",
            "itunes:author": "NYT",
            "language": "en",
        },
        [
            {
                "enclosureUrl": EP_AGENTS,
                "feedXmlUrl": HARD_FORK_XML,
                "title": "AI Agents Everywhere",
                "description": (
                    "<p>We talk about <a href='https://x.example'>autonomous "
                    "agents</a> and do interviews.</p>"
                ),
                "pubDate": "2026-08-30T08:00:00+00:00",
                "itunes:duration": "01:02:03",
                "itunes:episode": "101",
                "podcast:transcript:url": TRANSCRIPT_URL,
                "podcast:transcript:type": "text/vtt",
            },
            {
                "enclosureUrl": EP_CRYPTO,
                "feedXmlUrl": HARD_FORK_XML,
                "title": "Crypto Winter Returns",
                "description": "Bitcoin and the market.",
                "pubDate": "2026-09-04T08:00:00+00:00",
                "itunes:duration": "3600",
            },
            {
                "enclosureUrl": EP_UNHEARD,
                "feedXmlUrl": HARD_FORK_XML,
                "title": "Unheard Episode",
                "description": "Nothing here.",
                "pubDate": "2026-09-05T08:00:00+00:00",
            },
            {
                "enclosureUrl": EP_FEED_ONLY,
                "feedXmlUrl": HARD_FORK_XML,
                "title": "Interviewing the Agents",
                "description": "A bonus interview episode.",
                "pubDate": "2026-09-08T08:00:00+00:00",
            },
        ],
    )
    store.save_extended_feed_and_episodes(
        {"xmlUrl": OLD_SHOW_XML, "title": "Old Show", "description": "Gone"},
        [
            {
                "enclosureUrl": EP_OLD,
                "feedXmlUrl": OLD_SHOW_XML,
                "title": "Old Times",
                "description": "Agents of history.",
                "pubDate": "2024-12-30T08:00:00+00:00",
            },
        ],
    )
    store.db.close()
