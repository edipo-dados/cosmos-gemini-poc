-- 90 dias corridos [as_of - 89, as_of], as_of = DATA_END_DATE
SELECT '' AS key, count(DISTINCT customer_id)::text AS value
FROM {schema}.orders
WHERE status IN ('paid', 'refunded')
  AND order_date BETWEEN CAST(:data_end_date AS date) - 89 AND CAST(:data_end_date AS date)
