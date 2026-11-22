SELECT '' AS key, CAST(
  CAST(
    COALESCE((SELECT SUM(i.line_total) FROM fact_order_items i JOIN fact_orders o ON o.order_id = i.order_id WHERE o.is_paid), 0)
  - COALESCE((SELECT SUM(r.refund_amount) FROM fact_refunds r JOIN fact_orders o ON o.order_id = r.order_id
              WHERE r.status = 'completed' AND o.is_paid), 0) AS DOUBLE)
  / NULLIF((SELECT COUNT(*) FROM fact_orders WHERE is_paid), 0) AS VARCHAR) AS value
