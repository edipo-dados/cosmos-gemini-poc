SELECT '' AS key,
  (count(*) FILTER (WHERE status = 'cancelled')::float8 / NULLIF(count(*), 0))::text AS value
FROM {schema}.orders
