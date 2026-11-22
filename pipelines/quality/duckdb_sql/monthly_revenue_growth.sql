WITH months AS (
  SELECT CAST(UNNEST(generate_series(date_trunc('month', MIN(order_date)), date_trunc('month', MAX(order_date)),
                                     INTERVAL 1 MONTH)) AS DATE) AS m
  FROM fact_orders
), net AS (
  SELECT date_trunc('month', o.order_date) AS m,
         SUM(i.line_total - COALESCE(r.refund_amount, 0)) AS net
  FROM fact_orders o
  JOIN fact_order_items i ON i.order_id = o.order_id
  LEFT JOIN fact_refunds r ON r.order_item_id = i.order_item_id AND r.status = 'completed'
  WHERE o.is_paid
  GROUP BY 1
), series AS (
  SELECT months.m, COALESCE(net.net, 0) AS net FROM months LEFT JOIN net ON net.m = months.m
)
SELECT strftime(m, '%Y-%m') AS key,
       CAST(CAST(net AS DOUBLE) / NULLIF(LAG(net) OVER (ORDER BY m), 0) - 1 AS VARCHAR) AS value
FROM series
ORDER BY m
