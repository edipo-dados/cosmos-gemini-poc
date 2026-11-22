SELECT 'refund_before_order' AS issue, r.refund_id::text AS row_id
FROM {schema}.refunds r
JOIN {schema}.order_items i ON i.order_item_id = r.order_item_id
JOIN {schema}.orders o ON o.order_id = i.order_id
WHERE r.refunded_at < o.order_date
UNION ALL
SELECT 'order_in_future', order_id::text
FROM {schema}.orders
WHERE order_date > CAST(:data_end_date AS date)
UNION ALL
SELECT 'payment_before_order', p.payment_id::text
FROM {schema}.payments p
JOIN {schema}.orders o ON o.order_id = p.order_id
WHERE p.paid_at < o.order_date
