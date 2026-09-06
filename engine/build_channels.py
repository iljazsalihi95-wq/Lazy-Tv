import json
import re
import ssl
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# LAZYTV CHANNEL BUILDER
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

SOURCES_FILE = ROOT / "data" / "sources.json"
OUTPUT_FILE = ROOT / "data" / "channels.json"

DOWNLOAD_TIMEOUT = 15
CHECK_TIMEOUT = 7
MAX_WORKERS = 20

DEFAULT_UA = (
    "Mozilla/5.0 (Linux; Android 13) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Mobile Safari/537.36"
)

ssl_context = ssl.create_default_context()


# ============================================================
# HELPERS
# ============================================================

def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_country(value):
    return clean(value).upper()


def normalize_language(value):
    return clean(value).lower()


def attr(text, name):
    """
    Lexon:
    tvg-id="..."
    tvg-logo="..."
    group-title="..."
    tvg-language="..."
    """
    pattern = rf'{re.escape(name)}="([^"]*)"'
    match = re.search(pattern, text, flags=re.I)

    if match:
        return clean(match.group(1))

    return ""


def channel_name(extinf):
    """
    Emri zakonisht është pas presjes:
    #EXTINF:-1 ...,RTK 1
    """
    if "," in extinf:
        return clean(extinf.split(",", 1)[1])

    return "TV"


# ============================================================
# DOWNLOAD M3U
# ============================================================

def download_text(url):

    request = Request(
        url,
        headers={
            "User-Agent": DEFAULT_UA,
            "Accept": "*/*"
        }
    )

    with urlopen(
        request,
        timeout=DOWNLOAD_TIMEOUT,
        context=ssl_context
    ) as response:

        raw = response.read()

    return raw.decode(
        "utf-8",
        errors="ignore"
    )


# ============================================================
# PARSE M3U
# ============================================================

def parse_m3u(text, source):

    channels = []

    current = None

    pending_user_agent = ""
    pending_referrer = ""

    lines = text.splitlines()

    for raw_line in lines:

        line = raw_line.strip()

        if not line:
            continue


        # ----------------------------------------------------
        # CHANNEL INFO
        # ----------------------------------------------------

        if line.startswith("#EXTINF"):

            current = {
                "name": channel_name(line),

                "tvg_id": attr(
                    line,
                    "tvg-id"
                ),

                "logo": attr(
                    line,
                    "tvg-logo"
                ),

                "group": attr(
                    line,
                    "group-title"
                ),

                "language": (
                    attr(
                        line,
                        "tvg-language"
                    )
                    or source.get(
                        "language",
                        ""
                    )
                ),

                "country": source.get(
                    "country",
                    ""
                ),

                "source": source.get(
                    "name",
                    source.get(
                        "id",
                        ""
                    )
                ),

                "source_id": source.get(
                    "id",
                    ""
                ),

                "url": "",

                "user_agent": "",

                "referer": ""
            }

            pending_user_agent = ""
            pending_referrer = ""

            continue


        # ----------------------------------------------------
        # VLC USER AGENT
        # ----------------------------------------------------

        if line.lower().startswith(
            "#extvlcopt:http-user-agent="
        ):

            pending_user_agent = clean(
                line.split(
                    "=",
                    1
                )[1]
            )

            continue


        # ----------------------------------------------------
        # VLC REFERRER
        # ----------------------------------------------------

        if (
            line.lower().startswith(
                "#extvlcopt:http-referrer="
            )
            or
            line.lower().startswith(
                "#extvlcopt:http-referer="
            )
        ):

            pending_referrer = clean(
                line.split(
                    "=",
                    1
                )[1]
            )

            continue


        # ----------------------------------------------------
        # KODIPROP USER AGENT
        # ----------------------------------------------------

        if "user-agent=" in line.lower():

            try:

                pending_user_agent = clean(
                    line.split(
                        "user-agent=",
                        1
                    )[1]
                )

            except Exception:
                pass

            continue


        # ----------------------------------------------------
        # URL
        # ----------------------------------------------------

        if (
            current
            and
            not line.startswith("#")
        ):

            url = clean(line)

            # Disa M3U përdorin:
            # URL|User-Agent=xxx&Referer=xxx

            headers_part = ""

            if "|" in url:

                url, headers_part = url.split(
                    "|",
                    1
                )

                url = clean(url)


                for item in headers_part.split("&"):

                    if "=" not in item:
                        continue

                    key, value = item.split(
                        "=",
                        1
                    )

                    key = key.strip().lower()
                    value = value.strip()


                    if key in (
                        "user-agent",
                        "user_agent"
                    ):
                        pending_user_agent = value


                    elif key in (
                        "referer",
                        "referrer"
                    ):
                        pending_referrer = value


            if not url.lower().startswith(
                (
                    "http://",
                    "https://",
                    "rtsp://",
                    "rtmp://"
                )
            ):

                current = None
                continue


            current["url"] = url

            current["user_agent"] = (
                pending_user_agent
                or DEFAULT_UA
            )

            current["referer"] = (
                pending_referrer
            )


            channels.append(current)

            current = None

            pending_user_agent = ""
            pending_referrer = ""


    return channels


# ============================================================
# STREAM TYPE
# ============================================================

def stream_type(url):

    u = clean(url).lower()

    if ".m3u8" in u:
        return "hls"

    if ".mpd" in u:
        return "dash"

    if ".mp4" in u:
        return "mp4"

    if ".m4v" in u:
        return "video"

    if ".webm" in u:
        return "video"

    if ".mov" in u:
        return "video"

    if ".mkv" in u:
        return "video"

    if u.startswith("rtsp://"):
        return "rtsp"

    if u.startswith("rtmp://"):
        return "rtmp"

    return "stream"


# ============================================================
# BASIC STREAM CHECK
# ============================================================

def check_stream(channel):

    url = channel.get(
        "url",
        ""
    )

    if not url:
        return False


    # Browseri ynë nuk i luan direkt këto.
    # I ruajmë vetëm nëse më vonë përdorim native player.

    if url.startswith(
        (
            "rtsp://",
            "rtmp://"
        )
    ):
        return True


    headers = {
        "User-Agent": (
            channel.get(
                "user_agent"
            )
            or DEFAULT_UA
        ),

        "Accept": "*/*"
    }


    referer = channel.get(
        "referer",
        ""
    )

    if referer:
        headers["Referer"] = referer


    try:

        request = Request(
            url,
            headers=headers
        )


        with urlopen(
            request,
            timeout=CHECK_TIMEOUT,
            context=ssl_context
        ) as response:

            status = getattr(
                response,
                "status",
                200
            )

            if status < 200 or status >= 400:
                return False


            # Lexojmë vetëm pak bytes.
            # Nuk shkarkojmë videon.

            response.read(512)

            return True


    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        OSError
    ):

        return False


    except Exception:

        return False


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate(channels):

    result = []

    seen_urls = set()

    for channel in channels:

        url = clean(
            channel.get(
                "url"
            )
        )

        if not url:
            continue


        key = url.lower()

        if key in seen_urls:
            continue


        seen_urls.add(key)

        result.append(channel)


    return result


# ============================================================
# LOAD SOURCES
# ============================================================

def load_sources():

    if not SOURCES_FILE.exists():

        raise FileNotFoundError(
            f"Nuk u gjet: {SOURCES_FILE}"
        )


    with SOURCES_FILE.open(
        "r",
        encoding="utf-8"
    ) as f:

        data = json.load(f)


    if isinstance(data, list):
        sources = data

    else:
        sources = data.get(
            "sources",
            []
        )


    return [
        source
        for source in sources
        if source.get(
            "enabled",
            True
        )
    ]


# ============================================================
# BUILD
# ============================================================

def main():

    print(
        "======================================"
    )

    print(
        "LazyTV Channel Builder"
    )

    print(
        "======================================"
    )


    sources = load_sources()

    print(
        f"Sources aktive: {len(sources)}"
    )


    all_channels = []


    # --------------------------------------------------------
    # DOWNLOAD ALL SOURCES
    # --------------------------------------------------------

    for source in sources:

        name = source.get(
            "name",
            source.get(
                "id",
                "Source"
            )
        )

        url = source.get(
            "url",
            ""
        )


        if not url:
            continue


        print(
            f"\nDOWNLOAD: {name}"
        )


        try:

            text = download_text(url)

            channels = parse_m3u(
                text,
                source
            )

            print(
                f"  Found: {len(channels)}"
            )

            all_channels.extend(
                channels
            )


        except Exception as e:

            print(
                f"  ERROR: {e}"
            )


    # --------------------------------------------------------
    # DEDUPLICATE
    # --------------------------------------------------------

    all_channels = deduplicate(
        all_channels
    )


    print(
        f"\nUnique streams: {len(all_channels)}"
    )


    # --------------------------------------------------------
    # CHECK STREAMS
    # --------------------------------------------------------

    working = []


    print(
        "\nPo kontrollohen stream-et..."
    )


    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:


        future_map = {

            executor.submit(
                check_stream,
                channel
            ): channel

            for channel in all_channels

        }


        checked = 0


        for future in as_completed(
            future_map
        ):

            channel = future_map[
                future
            ]

            checked += 1


            try:

                ok = future.result()

            except Exception:

                ok = False


            if ok:

                channel["status"] = (
                    "online"
                )

                channel["type"] = (
                    stream_type(
                        channel.get(
                            "url",
                            ""
                        )
                    )
                )

                working.append(
                    channel
                )


            if (
                checked % 50 == 0
                or
                checked == len(
                    all_channels
                )
            ):

                print(
                    f"  Checked "
                    f"{checked}/"
                    f"{len(all_channels)}"
                    f" | Working "
                    f"{len(working)}"
                )


    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    working.sort(
        key=lambda ch: (
            normalize_country(
                ch.get(
                    "country"
                )
            ),

            clean(
                ch.get(
                    "group"
                )
            ).lower(),

            clean(
                ch.get(
                    "name"
                )
            ).lower()
        )
    )


    # --------------------------------------------------------
    # COUNTRIES
    # --------------------------------------------------------

    countries = {}


    for channel in working:

        country = normalize_country(
            channel.get(
                "country"
            )
        )

        if not country:
            country = "OTHER"


        countries[country] = (
            countries.get(
                country,
                0
            )
            + 1
        )


    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    output = {

        "version": 5,

        "updated": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),

        "total": len(
            working
        ),

        "checked": len(
            all_channels
        ),

        "countries": countries,

        "channels": working
    }


    OUTPUT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )


    with OUTPUT_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            output,
            f,
            ensure_ascii=False,
            indent=2
        )


    print(
        "\n======================================"
    )

    print(
        f"Checked: {len(all_channels)}"
    )

    print(
        f"Working: {len(working)}"
    )

    print(
        f"Saved: {OUTPUT_FILE}"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":
    main()
