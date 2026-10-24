"""Provider records normalized into catalogue identities and display metadata.

This boundary has no network or persistence side effects.
"""

import html
import re


class MediaError(Exception):
    pass


TMDB_GENRES = {
    "movie": {
        "Action": 28,
        "Adventure": 12,
        "Animation": 16,
        "Comedy": 35,
        "Crime": 80,
        "Documentary": 99,
        "Drama": 18,
        "Family": 10751,
        "Fantasy": 14,
        "History": 36,
        "Horror": 27,
        "Music": 10402,
        "Mystery": 9648,
        "Romance": 10749,
        "Science Fiction": 878,
        "TV Movie": 10770,
        "Thriller": 53,
        "War": 10752,
        "Western": 37,
    },
    "tv": {
        "Action & Adventure": 10759,
        "Animation": 16,
        "Comedy": 35,
        "Crime": 80,
        "Documentary": 99,
        "Drama": 18,
        "Family": 10751,
        "Kids": 10762,
        "Mystery": 9648,
        "News": 10763,
        "Reality": 10764,
        "Sci-Fi & Fantasy": 10765,
        "Soap": 10766,
        "Talk": 10767,
        "War & Politics": 10768,
        "Western": 37,
    },
}


def image_url(path, size="original"):
    return "https://image.tmdb.org/t/p/" + size + path if path else ""


def tmdb_title(d, kind):
    imdb = d.get("imdb_id") or d.get("external_ids", {}).get("imdb_id")
    return dict(
        id=imdb or f"tmdb:{kind}:{d['id']}",
        imdbId=imdb or "",
        tmdbId=d["id"],
        kind=kind,
        title=d.get("title") or d.get("name", ""),
        year=(d.get("release_date") or d.get("first_air_date", ""))[:4],
        poster=image_url(d.get("poster_path"), "w500"),
        backdrop=image_url(d.get("backdrop_path")),
        plot=d.get("overview", ""),
        runtime=d.get("runtime") or next(iter(d.get("episode_run_time", [])), 0),
        genres=[g["name"] for g in d.get("genres", [])]
        or [name for name, id in TMDB_GENRES[kind].items() if id in d.get("genre_ids", [])],
        countries=d.get("production_countries", []),
        rating=d.get("vote_average"),
        votes=d.get("vote_count", 0),
        ratings=[{"source": "TMDB", "value": round(d.get("vote_average", 0), 1)}],
    )


def omdb_title(d):
    def value(key):
        v = d.get(key)
        return v if v and v != "N/A" else ""

    def number(key):
        match = re.search(r"\d+(?:\.\d+)?", str(value(key)).replace(",", ""))
        return float(match[0]) if match else None

    def names(key):
        return [n.strip() for n in value(key).split(",") if n.strip()]

    return dict(
        id=d["imdbID"],
        imdbId=d["imdbID"],
        kind="tv" if d.get("Type") == "series" else "movie",
        title=value("Title"),
        year=int(number("Year")) if number("Year") else None,
        poster=value("Poster"),
        plot=value("Plot"),
        runtime=int(number("Runtime")) if number("Runtime") else None,
        genres=names("Genre"),
        countries=names("Country"),
        rating=number("imdbRating"),
        votes=int(number("imdbVotes")) if number("imdbVotes") else None,
        ratings=[
            dict(source=r["Source"], value=r["Value"])
            for r in d.get("Ratings", [])
            if r.get("Value") not in (None, "N/A", "")
        ],
        cast=[
            dict(id="", name=name, role=role)
            for field, role in [("Director", "Director"), ("Writer", "Writer"), ("Actors", "Cast")]
            for name in names(field)
        ],
    )


def anilist_title(d, kind):
    mal_id = d.get("idMal")
    if not isinstance(mal_id, int) or mal_id <= 0:
        raise MediaError("Anime catalogue returned no MAL ID.")
    names = d.get("title") or {}
    picture = d.get("coverImage") or {}
    studios = (d.get("studios") or {}).get("nodes") or []
    next_episode = (d.get("nextAiringEpisode") or {}).get("episode") or 0
    count = d.get("episodes") or max(0, next_episode - 1)
    plot = html.unescape(re.sub(r"<[^>]+>", " ", d.get("description") or ""))
    plot = re.sub(r"\s+", " ", plot).strip()
    trailer = d.get("trailer") or {}
    trailer_url = (
        "https://www.youtube.com/watch?v=" + trailer["id"]
        if trailer.get("site") == "youtube" and re.fullmatch(r"[\w-]{11}", trailer.get("id") or "")
        else ""
    )
    url = f"https://myanimelist.net/anime/{mal_id}"
    return dict(
        id=f"mal:{mal_id}",
        malId=mal_id,
        kind=kind,
        title=names.get("english") or names.get("romaji") or names.get("native") or "",
        originalTitle=names.get("native") or names.get("romaji") or "",
        aliases=list(
            dict.fromkeys(name for name in [*names.values(), *(d.get("synonyms") or [])] if name)
        ),
        format=d.get("format") or "",
        year=(d.get("startDate") or {}).get("year") or "",
        poster=picture.get("extraLarge") or picture.get("large") or "",
        backdrop=d.get("bannerImage") or "",
        plot=plot,
        runtime=d.get("duration"),
        genres=d.get("genres") or [],
        studios=[item["name"] for item in studios if item.get("name")],
        episodesCount=count,
        status=d.get("status") or "",
        rating=None,
        votes=0,
        malUrl=url,
        ratings=[],
        trailers=[dict(title="Trailer", url=trailer_url)] if trailer_url else [],
    )


def anime_related(rows, *, anilist_edges=False):
    result = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        node = row.get("node") or {}
        mal_id = node.get("idMal" if anilist_edges else "id")
        if not isinstance(mal_id, int) or mal_id <= 0 or mal_id in seen:
            continue
        seen.add(mal_id)
        names = node.get("title") if anilist_edges else None
        name = (
            names.get("english") or names.get("romaji") or names.get("native")
            if isinstance(names, dict)
            else node.get("title")
        )
        relation = (
            row.get("relationType") if anilist_edges else row.get("relation_type_formatted")
        ) or ""
        picture = node.get("coverImage" if anilist_edges else "main_picture") or {}
        start = node.get("startDate") if anilist_edges else node.get("start_date")
        format_name = node.get("format" if anilist_edges else "media_type") or ""
        result.append(
            dict(
                id=f"mal:{mal_id}",
                malId=mal_id,
                title=name or f"Anime {mal_id}",
                kind=anime_kind(format_name) if format_name else "",
                poster=picture.get("large") or picture.get("medium") or "",
                year=(start or {}).get("year") if isinstance(start, dict) else str(start or "")[:4],
                relation=str(relation).replace("_", " ").title(),
            )
        )
    return result


def anime_cast(data):
    result = []
    seen = set()
    for edge in (data.get("characters") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        character = (edge.get("node") or {}).get("name") or {}
        name = character.get("full") or ""
        for actor in edge.get("voiceActors") or []:
            actor_id = actor.get("id")
            if not isinstance(actor_id, int) or actor_id <= 0 or not name:
                continue
            key = (actor_id, name)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                dict(
                    id="",
                    name=(actor.get("name") or {}).get("full") or "",
                    role=f"{name} (voice)",
                    job="Actor",
                    department="Acting",
                    image=(actor.get("image") or {}).get("medium") or "",
                    url=f"https://anilist.co/staff/{actor_id}",
                )
            )
    for edge in (data.get("staff") or {}).get("edges") or []:
        if not isinstance(edge, dict):
            continue
        person = edge.get("node") or {}
        person_id = person.get("id")
        role = edge.get("role") or ""
        if not isinstance(person_id, int) or person_id <= 0:
            continue
        key = (person_id, role)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            dict(
                id="",
                name=(person.get("name") or {}).get("full") or "",
                role=role,
                job=("Writer" if role in ("Series Composition", "Script") else role),
                department="Crew",
                image=(person.get("image") or {}).get("medium") or "",
                url=f"https://anilist.co/staff/{person_id}",
            )
        )
    return [person for person in result if person["name"]]


def official_anime_title(d, kind):
    mal_id = d.get("id")
    if not isinstance(mal_id, int):
        raise MediaError("MAL returned an invalid title ID.")
    alternative = d.get("alternative_titles") or {}
    names = [
        d.get("title"),
        alternative.get("en"),
        alternative.get("ja"),
        *(alternative.get("synonyms") or []),
    ]
    url = f"https://myanimelist.net/anime/{mal_id}"
    score = d.get("mean")
    poster = d.get("main_picture") or {}
    duration = d.get("average_episode_duration")
    season = d.get("start_season") or {}
    premiere = (
        str(season.get("season") or "").title() + " " + str(season.get("year") or "")
    ).strip()
    source = str(d.get("source") or "").replace("_", " ").title()
    age_rating = {"g": "G", "pg": "PG", "pg_13": "PG-13", "r": "R-17+", "r+": "R+", "rx": "Rx"}.get(
        d.get("rating"), ""
    )
    return dict(
        id=f"mal:{mal_id}",
        malId=mal_id,
        kind=kind,
        title=alternative.get("en") or d.get("title") or "",
        originalTitle=alternative.get("ja") or d.get("title") or "",
        aliases=list(dict.fromkeys(name for name in names if name)),
        format=d.get("media_type") or "",
        year=str(d.get("start_date") or "")[:4],
        poster=poster.get("large") or poster.get("medium") or "",
        plot=d.get("synopsis") or "",
        runtime=round(duration / 60) if isinstance(duration, (int, float)) and duration else None,
        genres=[item["name"] for item in d.get("genres") or [] if item.get("name")],
        studios=[item["name"] for item in d.get("studios") or [] if item.get("name")],
        episodesCount=d.get("num_episodes") or 0,
        status=d.get("status") or "",
        premiere=premiere,
        sourceMaterial=source,
        ageRating=age_rating,
        background=d.get("background") or "",
        rating=score,
        votes=d.get("num_scoring_users") or 0,
        malUrl=url,
        ratings=[dict(source="MyAnimeList", value=score, url=url)] if score is not None else [],
    )


def anime_kind(format_name):
    return "movie" if str(format_name).lower() == "movie" else "tv"


def merge_ratings(*groups):
    aliases = {
        "internet movie database": "IMDb",
        "imdb": "IMDb",
        "rotten tomatoes": "Rotten Tomatoes",
        "tomatoes": "Rotten Tomatoes",
        "metacritic": "Metacritic",
        "tmdb": "TMDB",
    }
    ratings = {}
    for group in groups:
        for item in group:
            if item.get("value") in (None, "", "N/A"):
                continue
            source = aliases.get(item["source"].lower(), item["source"])
            ratings[source.lower()] = item | {"source": source}
    return list(ratings.values())


def clean_spoiler(text):
    text = re.sub(r"\[(?:edit|edit source)\]", "", text, flags=re.I)
    text = re.sub(r"^\s*(?:plot(?: synopsis)?|synopsis|story)\s*\n+", "", text, flags=re.I)
    return text.strip()


def tmdb_credits(data):
    credits = data.get("credits", {})
    return [
        dict(
            id="tmdb:" + str(p["id"]),
            name=p["name"],
            role=p.get("character") or "Actor",
            department="Acting",
            job="Actor",
            image=image_url(p.get("profile_path"), "w185"),
        )
        for p in credits.get("cast", [])
    ] + [
        dict(
            id="tmdb:" + str(p["id"]),
            name=p["name"],
            role=p.get("job", ""),
            job=p.get("job", ""),
            department=p.get("department", "Crew"),
            image=image_url(p.get("profile_path"), "w185"),
        )
        for p in credits.get("crew", [])
    ]


def credit_role(value):
    role = str(value or "").replace("_", " ").strip().lower()
    if role in ("actor", "actress", "acting", "cast", "self"):
        return "Actor"
    if role in ("director", "co-director", "co director", "series director", "directing"):
        return "Director"
    if role in ("writer", "writing", "screenplay", "story", "teleplay", "novel", "characters"):
        return "Writer"
    if "producer" in role or role == "production":
        return "Producer"
    return role.title() if role else ""


def tmdb_trailers(data):
    videos = [
        v
        for v in data.get("videos", {}).get("results", [])
        if v.get("site") == "YouTube" and v.get("type") == "Trailer" and v.get("key")
    ]
    videos.sort(key=lambda v: (not v.get("official", False), v.get("iso_639_1") != "en"))
    return list(
        {
            v["key"]: dict(
                title=v.get("name", "Trailer"), url="https://www.youtube.com/watch?v=" + v["key"]
            )
            for v in videos
        }.values()
    )
