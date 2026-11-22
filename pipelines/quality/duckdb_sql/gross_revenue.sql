SELECT '' AS key, CAST(COALESCE(SUM(i.line_total), 0) AS VARCHAR) AS value
FROM fact_order_items i
JOIN fact_orders o ON o.order_id = i.order_id
WHERE o.is_paid
