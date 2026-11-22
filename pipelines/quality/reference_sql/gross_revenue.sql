SELECT '' AS key, COALESCE(sum(i.line_total), 0)::text AS value
FROM {schema}.order_items i
JOIN {schema}.orders o ON o.order_id = i.order_id
WHERE o.status IN ('paid', 'refunded')
