SELECT o.order_id, p.payment_id
FROM {schema}.orders o
JOIN {schema}.payments p ON p.order_id = o.order_id
WHERE o.status = 'cancelled' AND p.status = 'captured'
