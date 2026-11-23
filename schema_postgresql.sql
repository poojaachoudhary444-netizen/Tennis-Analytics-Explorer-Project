-- Tennis Analytics schema (postgresql)
-- Generated from db.py - do not edit by hand; edit the models and re-run scripts/export_sql.py

CREATE TABLE categories (
	category_id VARCHAR(50) NOT NULL, 
	category_name VARCHAR(100) NOT NULL, 
	PRIMARY KEY (category_id)
);

CREATE TABLE competitors (
	competitor_id VARCHAR(50) NOT NULL, 
	name VARCHAR(100) NOT NULL, 
	country VARCHAR(100) NOT NULL, 
	country_code CHAR(3) NOT NULL, 
	abbreviation VARCHAR(10) NOT NULL, 
	PRIMARY KEY (competitor_id)
);
CREATE INDEX idx_competitors_country ON competitors (country);
CREATE INDEX idx_competitors_name ON competitors (name);

CREATE TABLE complexes (
	complex_id VARCHAR(50) NOT NULL, 
	complex_name VARCHAR(100) NOT NULL, 
	PRIMARY KEY (complex_id)
);

CREATE TABLE pipeline_runs (
	run_id SERIAL NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	run_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	notes VARCHAR(500), 
	PRIMARY KEY (run_id)
);

CREATE TABLE competitions (
	competition_id VARCHAR(50) NOT NULL, 
	competition_name VARCHAR(100) NOT NULL, 
	parent_id VARCHAR(50), 
	type VARCHAR(20) NOT NULL, 
	gender VARCHAR(10) NOT NULL, 
	category_id VARCHAR(50) NOT NULL, 
	PRIMARY KEY (competition_id), 
	FOREIGN KEY(category_id) REFERENCES categories (category_id)
);
CREATE INDEX idx_competitions_category ON competitions (category_id);
CREATE INDEX idx_competitions_gender ON competitions (gender);
CREATE INDEX idx_competitions_parent ON competitions (parent_id);
CREATE INDEX idx_competitions_type ON competitions (type);

CREATE TABLE competitor_rankings (
	rank_id SERIAL NOT NULL, 
	rank INTEGER NOT NULL, 
	movement INTEGER NOT NULL, 
	points INTEGER NOT NULL, 
	competitions_played INTEGER NOT NULL, 
	competitor_id VARCHAR(50) NOT NULL, 
	ranking_type VARCHAR(20) NOT NULL, 
	year INTEGER NOT NULL, 
	week INTEGER NOT NULL, 
	gender VARCHAR(10) NOT NULL, 
	PRIMARY KEY (rank_id), 
	CONSTRAINT uq_ranking_snapshot UNIQUE (competitor_id, ranking_type, year, week, gender), 
	FOREIGN KEY(competitor_id) REFERENCES competitors (competitor_id)
);
CREATE INDEX idx_rankings_competitor ON competitor_rankings (competitor_id);
CREATE INDEX idx_rankings_points ON competitor_rankings (points);
CREATE INDEX idx_rankings_rank ON competitor_rankings (rank);
CREATE INDEX idx_rankings_snapshot ON competitor_rankings (year, week, gender);

CREATE TABLE venues (
	venue_id VARCHAR(50) NOT NULL, 
	venue_name VARCHAR(100) NOT NULL, 
	city_name VARCHAR(100) NOT NULL, 
	country_name VARCHAR(100) NOT NULL, 
	country_code CHAR(3) NOT NULL, 
	timezone VARCHAR(100) NOT NULL, 
	complex_id VARCHAR(50) NOT NULL, 
	PRIMARY KEY (venue_id), 
	FOREIGN KEY(complex_id) REFERENCES complexes (complex_id)
);
CREATE INDEX idx_venues_complex ON venues (complex_id);
CREATE INDEX idx_venues_country ON venues (country_name);
