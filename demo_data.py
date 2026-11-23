"""
DEMO DATA generator - NOT real tennis data.

SportRadar requires a personal API key, so this module fabricates small
datasets that have *exactly the same JSON structure* as the real API
responses. That lets you run and test the whole pipeline + Streamlit app
before you have a key. Everything it produces is fictional (names, points,
venues). Load real data with ``python run_pipeline.py --source api``.

The generated data deliberately includes the examples used in the project
brief (category "ITF Men", country "Chile", complex "Nacional", country
"Croatia", "ATP Vienna" parent/sub-competitions) so every SQL query returns
rows.
"""

from __future__ import annotations

import random
from datetime import date

SEED = 42

CATEGORIES = [
    ("sr:category:3", "ATP"),
    ("sr:category:6", "WTA"),
    ("sr:category:72", "Challenger"),
    ("sr:category:76", "Davis Cup"),
    ("sr:category:74", "Billie Jean King Cup"),
    ("sr:category:785", "ITF Men"),
    ("sr:category:213", "ITF Women"),
    ("sr:category:2516", "UTR Men"),
    ("sr:category:2517", "UTR Women"),
]

# (country, ISO3 code, venue city, timezone)
COUNTRIES = [
    ("Croatia", "HRV", "Zagreb", "Europe/Zagreb"),
    ("USA", "USA", "Cincinnati", "America/New_York"),
    ("Australia", "AUS", "Melbourne", "Australia/Melbourne"),
    ("Spain", "ESP", "Madrid", "Europe/Madrid"),
    ("France", "FRA", "Paris", "Europe/Paris"),
    ("Great Britain", "GBR", "London", "Europe/London"),
    ("Germany", "DEU", "Hamburg", "Europe/Berlin"),
    ("Italy", "ITA", "Rome", "Europe/Rome"),
    ("Argentina", "ARG", "Buenos Aires", "America/Argentina/Buenos_Aires"),
    ("El Salvador", "SLV", "San Salvador", "America/El_Salvador"),
    ("Netherlands", "NLD", "Rotterdam", "Europe/Amsterdam"),
    ("Brazil", "BRA", "Sao Paulo", "America/Sao_Paulo"),
    ("Chile", "CHL", "Santiago", "America/Santiago"),
    ("Czechia", "CZE", "Prague", "Europe/Prague"),
    ("Poland", "POL", "Warsaw", "Europe/Warsaw"),
    ("Austria", "AUT", "Vienna", "Europe/Vienna"),
    ("Japan", "JPN", "Tokyo", "Asia/Tokyo"),
    ("India", "IND", "Pune", "Asia/Kolkata"),
    ("Canada", "CAN", "Montreal", "America/Toronto"),
    ("Mexico", "MEX", "Acapulco", "America/Mexico_City"),
]

FIRST_M = ["Marco", "Luka", "Tomas", "Andre", "Felix", "Nico", "Pablo", "Ivan", "Kai", "Rafael", "Joel", "Dario", "Milan", "Oscar", "Hugo"]
FIRST_W = ["Anna", "Elena", "Marta", "Sofia", "Petra", "Lina", "Clara", "Nadia", "Irina", "Maya", "Zoe", "Alba", "Katja", "Dora", "Vera"]
LAST = ["Novak", "Marin", "Duarte", "Keller", "Rossi", "Sato", "Bauer", "Lopez", "Horvat", "Silva", "Moreau", "Kovac", "Petrov", "Reyes", "Fischer",
        "Costa", "Jensen", "Varga", "Ortega", "Lindqvist", "Almeida", "Brandt", "Mendez", "Novotny", "Wagner", "Torres", "Ivanov", "Santos", "Becker", "Pavlic"]


def _competitions(rng: random.Random) -> dict:
    competitions = []
    seq = 1000

    def add(name, ctype, gender, cat_id, cat_name, parent_id=None, level=None):
        nonlocal seq
        seq += 1
        item = {"id": f"sr:competition:{seq}", "name": name, "type": ctype, "gender": gender,
                "category": {"id": cat_id, "name": cat_name}}
        if parent_id:
            item["parent_id"] = parent_id
        if level:
            item["level"] = level
        competitions.append(item)
        return item["id"]

    # Tournaments: one parent + singles + doubles children (ATP Vienna example from the brief)
    atp_events = ["Vienna, Austria", "Basel, Switzerland", "Rotterdam, Netherlands", "Hamburg, Germany", "Bucharest, Romania",
                  "Santiago, Chile", "Acapulco, Mexico", "Pune, India", "Zagreb, Croatia", "Tokyo, Japan"]
    for place in atp_events:
        parent = add(f"ATP {place} Men", "mixed", "men", "sr:category:3", "ATP", level="atp_250")
        add(f"ATP {place} Men Singles", "singles", "men", "sr:category:3", "ATP", parent, "atp_250")
        add(f"ATP {place} Men Doubles", "doubles", "men", "sr:category:3", "ATP", parent, "atp_250")
    for place in ["Cincinnati, USA", "Madrid, Spain", "Rome, Italy", "Monterrey, Mexico", "Prague, Czechia", "Warsaw, Poland"]:
        parent = add(f"WTA {place} Women", "mixed", "women", "sr:category:6", "WTA", level="wta_500")
        add(f"WTA {place} Women Singles", "singles", "women", "sr:category:6", "WTA", parent, "wta_500")
        add(f"WTA {place} Women Doubles", "doubles", "women", "sr:category:6", "WTA", parent, "wta_500")

    # Challenger / ITF / UTR circuits - many standalone (top-level) events
    for i in range(1, 16):
        place = rng.choice(COUNTRIES)
        add(f"ATP Challenger {place[2]}, {place[0]} Men Singles", "singles", "men", "sr:category:72", "Challenger")
        if i % 2 == 0:
            add(f"ATP Challenger {place[2]}, {place[0]} Men Doubles", "doubles", "men", "sr:category:72", "Challenger")
    for i in range(1, 41):
        place = rng.choice(COUNTRIES)
        add(f"ITF M25 {place[2]}, {place[0]} Men Singles", "singles", "men", "sr:category:785", "ITF Men")
        add(f"ITF M25 {place[2]}, {place[0]} Men Doubles", "doubles", "men", "sr:category:785", "ITF Men")
    for i in range(1, 31):
        place = rng.choice(COUNTRIES)
        add(f"ITF W15 {place[2]}, {place[0]} Women Singles", "singles", "women", "sr:category:213", "ITF Women")
        add(f"ITF W15 {place[2]}, {place[0]} Women Doubles", "doubles", "women", "sr:category:213", "ITF Women")
    for i in range(1, 11):
        add(f"UTR Pro Tennis Tour Men {i:02d}", "singles", "men", "sr:category:2516", "UTR Men")
        add(f"UTR Pro Tennis Tour Women {i:02d}", "singles", "women", "sr:category:2517", "UTR Women")
    add("Davis Cup", "mixed", "men", "sr:category:76", "Davis Cup")
    add("Billie Jean King Cup", "mixed", "women", "sr:category:74", "Billie Jean King Cup")
    add("Mixed Team Cup", "mixed_doubles", "mixed", "sr:category:3", "ATP")

    return {"generated_at": f"{date.today().isoformat()}T00:00:00+00:00", "competitions": competitions}


def _complexes(rng: random.Random) -> dict:
    complexes = []
    venue_seq = 5000
    # Example from the brief: complex "Nacional" in Chile with several venues
    plan = [("Nacional", "Chile", "CHL", "Santiago", "America/Santiago", 3)]
    for country, code, city, tz in COUNTRIES:
        if country == "Chile":
            continue
        for k in range(rng.choice([1, 1, 2])):
            plan.append((f"{city} {rng.choice(['Tennis Club', 'Sports Park', 'Arena', 'Racquet Centre'])}", country, code, city, tz,
                         rng.choice([1, 1, 2, 3, 4])))

    for idx, (name, country, code, city, tz, n_venues) in enumerate(plan, start=1):
        venues = []
        for v in range(1, n_venues + 1):
            venue_seq += 1
            venue = {"id": f"sr:venue:{venue_seq}", "name": rng.choice(["Center Court", "Court", "Stadium Court", "Arena"]) + f" {v}",
                     "city_name": city, "country_name": country, "country_code": code, "timezone": tz}
            if rng.random() < 0.15:  # real feeds sometimes omit fields - exercise the defaults
                venue.pop("timezone")
            venues.append(venue)
        complexes.append({"id": f"sr:complex:{idx}", "name": name, "venues": venues})
    return {"generated_at": f"{date.today().isoformat()}T00:00:00+00:00", "complexes": complexes}


def _player(rng: random.Random, index: int, women: bool, country_weights: list[int]) -> dict:
    country, code, _, _ = rng.choices(COUNTRIES, weights=country_weights, k=1)[0]
    last = rng.choice(LAST)
    first = rng.choice(FIRST_W if women else FIRST_M)
    return {"id": f"sr:competitor:{(200000 if women else 100000) + index}", "name": f"{last}, {first}",
            "country": country, "country_code": code, "abbreviation": last[:3].upper()}


def _doubles_rankings(rng: random.Random, size: int = 150) -> dict:
    iso = date.today().isocalendar()
    weights = [8 if c[0] in ("Croatia", "USA", "Spain", "Argentina") else 3 for c in COUNTRIES]
    rankings = []
    for type_id, name, gender, women in ((2, "ATP", "men", False), (3, "WTA", "women", True)):
        entries, points, rank = [], 9000 + rng.randint(-500, 500), 1
        for i in range(size):
            entries.append({
                "rank": rank,
                "movement": rng.choice([0, 0, 0, 0, 0, 1, -1, 2, -2, 3, -3, 5, -6, 8]),
                "points": points,
                "competitions_played": rng.randint(6, 32),
                "competitor": _player(rng, i, women, weights),
            })
            if rng.random() > 0.08:  # occasionally keep the same rank (ties, as in the real feed)
                rank = i + 2
            points = max(150, points - rng.randint(15, 160))
        rankings.append({"type_id": type_id, "name": name, "year": iso.year, "week": iso.week, "gender": gender,
                         "competitor_rankings": entries})
    return {"generated_at": f"{date.today().isoformat()}T00:00:00+00:00", "rankings": rankings}


def generate_demo_payloads(seed: int = SEED) -> dict[str, dict]:
    """Return ``{'competitions': ..., 'complexes': ..., 'doubles_rankings': ...}`` in API format."""
    rng = random.Random(seed)
    return {
        "competitions": _competitions(rng),
        "complexes": _complexes(rng),
        "doubles_rankings": _doubles_rankings(rng),
    }
