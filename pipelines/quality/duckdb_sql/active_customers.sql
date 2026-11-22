SELECT '' AS key, CAST(COUNT(DISTINCT customer_id) AS VARCHAR) AS value
FROM fact_orders
WHERE is_paid
  AND order_date BETWEEN CAST($data_end_date AS DATE) - 89 AND CAST($data_end_date AS DATE)
