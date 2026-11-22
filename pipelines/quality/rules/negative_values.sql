SELECT 'products' AS table_name, product_id::text AS row_id FROM {schema}.products WHERE unit_price < 0
UNION ALL
SELECT 'orders', order_id::text FROM {schema}.orders WHERE total_amount < 0
UNION ALL
SELECT 'order_items', order_item_id::text FROM {schema}.order_items
  WHERE quantity <= 0 OR unit_price < 0 OR line_total < 0
UNION ALL
SELECT 'payments', payment_id::text FROM {schema}.payments WHERE amount < 0
UNION ALL
SELECT 'refunds', refund_id::text FROM {schema}.refunds WHERE refund_amount < 0
