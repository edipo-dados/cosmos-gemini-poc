SELECT o.order_id, o.customer_id
FROM {schema}.orders o
LEFT JOIN {schema}.customers c ON c.customer_id = o.customer_id
WHERE c.customer_id IS NULL
