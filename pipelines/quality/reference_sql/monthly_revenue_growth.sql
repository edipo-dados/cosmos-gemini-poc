-- crescimento da receita líquida mês a mês sobre calendário completo (mês sem venda vale 0)
WITH months AS (
  SELECT generate_series(date_trunc('month', min(order_date)), date_trunc('month', max(order_date)),
                         interval '1 month')::date AS m
  FROM {schema}.orders
), net AS (
  SELECT date_trunc('month', o.order_date)::date AS m,
         sum(i.line_total - COALESCE(r.refund_amount, 0)) AS net
  FROM {schema}.orders o
  JOIN {schema}.order_items i ON i.order_id = o.order_id
  LEFT JOIN {schema}.refunds r ON r.order_item_id = i.order_item_id AND r.status = 'completed'
  WHERE o.status IN ('paid', 'refunded')
  GROUP BY 1
), series AS (
  SELECT months.m, COALESCE(net.net, 0) AS net
  FROM months LEFT JOIN net ON net.m = months.m
)
SELECT to_char(m, 'YYYY-MM') AS key,
       (net::float8 / NULLIF(lag(net) OVER (ORDER BY m), 0) - 1)::text AS value
FROM series
ORDER BY m
