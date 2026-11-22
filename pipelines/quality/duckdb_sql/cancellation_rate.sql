SELECT '' AS key,
  CAST(CAST(COUNT(*) FILTER (WHERE status = 'cancelled') AS DOUBLE) / NULLIF(COUNT(*), 0) AS VARCHAR) AS value
FROM fact_orders
