SELECT '' AS key, CAST(COALESCE(SUM(refund_amount), 0) AS VARCHAR) AS value
FROM fact_refunds
WHERE status = 'completed'
