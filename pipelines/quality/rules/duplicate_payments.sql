SELECT order_id, count(*) AS payments
FROM {schema}.payments
GROUP BY order_id
HAVING count(*) > 1
