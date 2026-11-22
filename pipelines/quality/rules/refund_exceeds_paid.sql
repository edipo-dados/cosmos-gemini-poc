-- Reembolsos efetivados acima do valor capturado do pedido, ou acima do total do item.
WITH refunded AS (
  SELECT i.order_id,
         sum(r.refund_amount) AS refunded,
         bool_or(r.refund_amount > i.line_total) AS item_exceeded
  FROM {schema}.refunds r
  JOIN {schema}.order_items i ON i.order_item_id = r.order_item_id
  WHERE r.status = 'completed'
  GROUP BY i.order_id
), paid AS (
  SELECT order_id, sum(amount) AS paid
  FROM {schema}.payments
  WHERE status = 'captured'
  GROUP BY order_id
)
SELECT f.order_id
FROM refunded f
LEFT JOIN paid p ON p.order_id = f.order_id
WHERE f.refunded > COALESCE(p.paid, 0) OR f.item_exceeded
