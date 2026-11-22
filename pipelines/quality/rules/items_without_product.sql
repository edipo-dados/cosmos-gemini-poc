SELECT i.order_item_id, i.product_id
FROM {schema}.order_items i
LEFT JOIN {schema}.products p ON p.product_id = i.product_id
WHERE p.product_id IS NULL
