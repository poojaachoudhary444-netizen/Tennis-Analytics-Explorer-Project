-- =====================================================================
-- Game Analytics: Unlocking Tennis Data with SportRadar API
-- SQL analysis queries (20) - works on MySQL, PostgreSQL and SQLite
-- Tables: categories, competitions, complexes, venues, competitors, competitor_rankings
-- Note: 'rank' is a reserved word in MySQL 8, so it is always written r.rank
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1) COMPETITIONS DATA
-- ---------------------------------------------------------------------

-- C1. List all competitions along with their category name
-- INNER JOIN of competitions to categories through the category_id foreign key.
SELECT c.competition_id, c.competition_name, c.type, c.gender, cat.category_name
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
ORDER BY cat.category_name, c.competition_name;

-- C2. Count the number of competitions in each category
-- LEFT JOIN + GROUP BY so categories with zero competitions would still appear.
SELECT cat.category_name, COUNT(c.competition_id) AS competition_count
FROM categories cat
LEFT JOIN competitions c ON c.category_id = cat.category_id
GROUP BY cat.category_id, cat.category_name
ORDER BY competition_count DESC;

-- C3. Find all competitions of type 'doubles'
-- Simple filter on the type column (served by idx_competitions_type).
SELECT c.competition_id, c.competition_name, c.gender, cat.category_name
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
WHERE c.type = 'doubles'
ORDER BY cat.category_name, c.competition_name;

-- C4. Get competitions that belong to a specific category (e.g. ITF Men)
-- Parameterised: change :category_name to any category (ATP, WTA, Challenger, ITF Women ...).
SELECT c.competition_id, c.competition_name, c.type, c.gender
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
WHERE cat.category_name = 'ITF Men'
ORDER BY c.competition_name;

-- C5. Identify parent competitions and their sub-competitions
-- Self-join: the child's parent_id points at the parent's competition_id (e.g. ATP Vienna -> Singles / Doubles).
SELECT p.competition_id   AS parent_competition_id,
       p.competition_name AS parent_competition,
       ch.competition_id   AS sub_competition_id,
       ch.competition_name AS sub_competition,
       ch.type             AS sub_competition_type
FROM competitions p
JOIN competitions ch ON ch.parent_id = p.competition_id
ORDER BY p.competition_name, ch.competition_name;

-- C6. Analyze the distribution of competition types by category
-- Two-column GROUP BY gives a category x type cross-tab in long format.
SELECT cat.category_name, c.type, COUNT(*) AS competition_count
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
GROUP BY cat.category_name, c.type
ORDER BY cat.category_name, competition_count DESC;

-- C7. List all competitions with no parent (top-level competitions)
-- IS NULL (not = NULL) is required to test for a missing parent.
SELECT c.competition_id, c.competition_name, c.type, c.gender, cat.category_name
FROM competitions c
JOIN categories cat ON cat.category_id = c.category_id
WHERE c.parent_id IS NULL
ORDER BY cat.category_name, c.competition_name;


-- ---------------------------------------------------------------------
-- 2) COMPLEXES & VENUES DATA
-- ---------------------------------------------------------------------

-- V1. List all venues along with their associated complex name
-- INNER JOIN of venues to complexes through complex_id.
SELECT v.venue_id, v.venue_name, v.city_name, v.country_name, cx.complex_name
FROM venues v
JOIN complexes cx ON cx.complex_id = v.complex_id
ORDER BY cx.complex_name, v.venue_name;

-- V2. Count the number of venues in each complex
-- GROUP BY complex with COUNT of its venues.
SELECT cx.complex_name, COUNT(v.venue_id) AS venue_count
FROM complexes cx
LEFT JOIN venues v ON v.complex_id = cx.complex_id
GROUP BY cx.complex_id, cx.complex_name
ORDER BY venue_count DESC, cx.complex_name;

-- V3. Get details of venues in a specific country (e.g. Chile)
-- Parameterised on :country_name (served by idx_venues_country).
SELECT v.venue_id, v.venue_name, v.city_name, v.country_name, v.country_code, v.timezone
FROM venues v
WHERE v.country_name = 'Chile'
ORDER BY v.city_name, v.venue_name;

-- V4. Identify all venues and their timezones
-- Ordered by timezone so venues in the same zone sit together.
SELECT v.venue_name, v.city_name, v.country_name, v.timezone
FROM venues v
ORDER BY v.timezone, v.country_name, v.venue_name;

-- V5. Find complexes that have more than one venue
-- HAVING filters on the aggregate (WHERE cannot, because it runs before grouping).
SELECT cx.complex_name, COUNT(v.venue_id) AS venue_count
FROM complexes cx
JOIN venues v ON v.complex_id = cx.complex_id
GROUP BY cx.complex_id, cx.complex_name
HAVING COUNT(v.venue_id) > 1
ORDER BY venue_count DESC, cx.complex_name;

-- V6. List venues grouped by country
-- A window function counts the venues per country while still listing every venue, grouped by country.
SELECT v.country_name,
       COUNT(*) OVER (PARTITION BY v.country_name) AS venues_in_country,
       v.city_name, v.venue_name
FROM venues v
ORDER BY v.country_name, v.city_name, v.venue_name;

-- V7. Find all venues for a specific complex (e.g. Nacional)
-- Parameterised on :complex_name.
SELECT cx.complex_name, v.venue_name, v.city_name, v.country_name, v.timezone
FROM venues v
JOIN complexes cx ON cx.complex_id = v.complex_id
WHERE cx.complex_name = 'Nacional'
ORDER BY v.venue_name;


-- ---------------------------------------------------------------------
-- 3) DOUBLES COMPETITOR RANKINGS DATA
-- ---------------------------------------------------------------------

-- R1. Get all competitors with their rank and points
-- Join rankings to competitor details; every stored weekly snapshot is returned.
SELECT c.name, c.country, r.ranking_type, r.gender, r.year, r.week,
       r.rank AS competitor_rank, r.points, r.movement, r.competitions_played
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
ORDER BY r.ranking_type, r.year DESC, r.week DESC, r.rank;

-- R2. Find competitors ranked in the top 5
-- Top 5 of the current (latest) week for each tour. Ties share a rank, so more than 5 rows can appear.
SELECT c.name, c.country, r.ranking_type, r.rank AS competitor_rank, r.points
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE r.rank <= 5
  AND r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings
                WHERE year = (SELECT MAX(year) FROM competitor_rankings))
ORDER BY r.ranking_type, r.rank, c.name;

-- R3. List competitors with no rank movement (stable rank)
-- movement = 0 means the same rank as the previous week.
SELECT c.name, c.country, r.ranking_type, r.rank AS competitor_rank, r.points, r.movement
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE r.movement = 0
  AND r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings
                WHERE year = (SELECT MAX(year) FROM competitor_rankings))
ORDER BY r.ranking_type, r.rank;

-- R4. Get the total points of competitors from a specific country (e.g. Croatia)
-- Parameterised on :country; totals are split by tour (ATP / WTA) because their points are not comparable.
SELECT c.country, r.ranking_type,
       COUNT(*)        AS ranked_competitors,
       SUM(r.points)   AS total_points
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE c.country = 'Croatia'
  AND r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings
                WHERE year = (SELECT MAX(year) FROM competitor_rankings))
GROUP BY c.country, r.ranking_type
ORDER BY total_points DESC;

-- R5. Count the number of competitors per country
-- GROUP BY country over the competitors dimension table.
SELECT c.country, c.country_code, COUNT(*) AS competitor_count
FROM competitors c
GROUP BY c.country, c.country_code
ORDER BY competitor_count DESC, c.country;

-- R6. Find competitors with the highest points in the current week
-- Correlated sub-query returns the top points scorer of each tour in the latest week (ties included).
SELECT c.name, c.country, r.ranking_type, r.gender, r.rank AS competitor_rank, r.points
FROM competitor_rankings r
JOIN competitors c ON c.competitor_id = r.competitor_id
WHERE r.year = (SELECT MAX(year) FROM competitor_rankings)
  AND r.week = (SELECT MAX(week) FROM competitor_rankings
                WHERE year = (SELECT MAX(year) FROM competitor_rankings))
  AND r.points = (SELECT MAX(r2.points)
                  FROM competitor_rankings r2
                  WHERE r2.ranking_type = r.ranking_type
                    AND r2.year = r.year AND r2.week = r.week)
ORDER BY r.points DESC;
