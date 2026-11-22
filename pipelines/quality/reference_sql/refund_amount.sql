SELECT '' AS key, COALESCE(sum(r.refund_amount), 0)::text AS value
FROM {schema}.refunds r
WHERE r.status = 'completed'
