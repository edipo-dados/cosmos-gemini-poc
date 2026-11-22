-- receita líquida / pedidos pagos distintos (NULL se não houver pedidos pagos)
SELECT '' AS key,
  ((COALESCE((SELECT sum(i.line_total) FROM {schema}.order_items i
              JOIN {schema}.orders o ON o.order_id = i.order_id
              WHERE o.status IN ('paid', 'refunded')), 0)
  - COALESCE((SELECT sum(r.refund_amount) FROM {schema}.refunds r
              JOIN {schema}.order_items i ON i.order_item_id = r.order_item_id
              JOIN {schema}.orders o ON o.order_id = i.order_id
              WHERE r.status = 'completed' AND o.status IN ('paid', 'refunded')), 0))::float8
  / NULLIF((SELECT count(*) FROM {schema}.orders WHERE status IN ('paid', 'refunded')), 0))::text AS value
