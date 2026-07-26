-- PJM transmission zone -> HIFLD utility service territory.
--
-- PJM will not publish node coordinates or network shapefiles (Critical Energy
-- Infrastructure Information), so zone geometry has to be rebuilt from the utility
-- territories the zones were drawn around. Every name below was verified to exist in
-- stg_utility_territory before being written here; see the coverage check at the bottom.
--
-- Several zones are unions: AEP and ATSI in particular are holding-company zones that
-- cover multiple operating utilities.

TRUNCATE dim_zone;

INSERT INTO dim_zone (zone_code, zone_label, utility_names) VALUES
  ('AECO',    'Atlantic City Electric',        ARRAY['ATLANTIC CITY ELECTRIC CO']),
  ('AEP',     'American Electric Power',       ARRAY['OHIO POWER CO',
                                                     'APPALACHIAN POWER CO',
                                                     'INDIANA MICHIGAN POWER CO',
                                                     'KENTUCKY POWER CO',
                                                     'WHEELING POWER CO']),
  ('APS',     'Allegheny Power Systems',       ARRAY['MONONGAHELA POWER CO',
                                                     'WEST PENN POWER COMPANY',
                                                     'THE POTOMAC EDISON COMPANY']),
  ('ATSI',    'American Transmission Systems', ARRAY['OHIO EDISON CO',
                                                     'CLEVELAND ELECTRIC ILLUM CO',
                                                     'THE TOLEDO EDISON CO',
                                                     'PENNSYLVANIA POWER CO']),
  ('BGE',     'Baltimore Gas & Electric',      ARRAY['BALTIMORE GAS & ELECTRIC CO']),
  ('COMED',   'Commonwealth Edison',           ARRAY['COMMONWEALTH EDISON CO']),
  ('DAY',     'Dayton Power & Light',          ARRAY['DAYTON POWER & LIGHT CO']),
  ('DEOK',    'Duke Energy Ohio/Kentucky',     ARRAY['DUKE ENERGY OHIO INC',
                                                     'DUKE ENERGY KENTUCKY']),
  ('DOM',     'Dominion',                      ARRAY['VIRGINIA ELECTRIC & POWER CO']),
  ('DPL',     'Delmarva Power & Light',        ARRAY['DELMARVA POWER']),
  ('DUQ',     'Duquesne Light',                ARRAY['DUQUESNE LIGHT CO']),
  ('EKPC',    'East Kentucky Power Coop',      ARRAY['EAST KENTUCKY POWER COOP, INC']),
  ('JCPL',    'Jersey Central Power & Light',  ARRAY['JERSEY CENTRAL POWER & LT CO']),
  ('METED',   'Metropolitan Edison',           ARRAY['METROPOLITAN EDISON CO']),
  ('OVEC',    'Ohio Valley Electric',          ARRAY['OHIO VALLEY ELECTRIC CORP']),
  ('PECO',    'PECO Energy',                   ARRAY['PECO ENERGY CO']),
  ('PENELEC', 'Pennsylvania Electric',         ARRAY['PENNSYLVANIA ELECTRIC CO']),
  ('PEPCO',   'Potomac Electric Power',        ARRAY['POTOMAC ELECTRIC POWER CO']),
  -- UGI has no PJM zone of its own; its territory sits inside PPL's and PJM prices it there.
  ('PPL',     'PPL Electric Utilities',        ARRAY['PPL ELECTRIC UTILITIES CORP',
                                                     'UGI UTILITIES, INC']),
  ('PSEG',    'Public Service Electric & Gas', ARRAY['PUBLIC SERVICE ELEC & GAS CO']),
  -- RECO (Rockland Electric) is a real PJM zone with ~24 nodes but does not appear in
  -- HIFLD's coverage of the PJM-footprint states. Left geometry-less on purpose: it drops
  -- off the map rather than being drawn somewhere invented.
  ('RECO',    'Rockland Electric',             ARRAY[]::text[]);

-- Dissolve each zone's constituent utilities into one polygon. Territories can overlap
-- slightly and carry topology errors, hence MakeValid on the way in and Buffer(0) after.
UPDATE dim_zone z
SET geom = sub.geom
FROM (
  SELECT z2.zone_code,
         ST_Multi(ST_Buffer(ST_Union(ST_MakeValid(u.geom)), 0.0)) AS geom
  FROM dim_zone z2
  JOIN stg_utility_territory u ON u.name = ANY(z2.utility_names)
  GROUP BY z2.zone_code
) sub
WHERE sub.zone_code = z.zone_code;

-- Coverage check: any zone with nodes but no geometry, or names that matched nothing.
\echo '=== zones with no geometry ==='
SELECT zone_code, zone_label, cardinality(utility_names) AS n_utilities
FROM dim_zone WHERE geom IS NULL ORDER BY zone_code;

\echo '=== crosswalk names that matched no HIFLD territory ==='
SELECT z.zone_code, n AS unmatched_utility
FROM dim_zone z, unnest(z.utility_names) AS n
WHERE NOT EXISTS (SELECT 1 FROM stg_utility_territory u WHERE u.name = n)
ORDER BY 1, 2;

\echo '=== zone areas (sanity: AEP and DOM should be the largest) ==='
SELECT zone_code,
       round((ST_Area(geom::geography) / 2589988.11)::numeric, 0) AS sq_mi
FROM dim_zone WHERE geom IS NOT NULL ORDER BY sq_mi DESC;
