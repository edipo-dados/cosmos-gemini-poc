-- Laboratório de defeitos: mesmas colunas, só PKs (sem FKs, CHECKs nem UNIQUEs),
-- para permitir linhas inválidas controladas. Nunca alimenta métricas oficiais.
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['categories','regions','customers','products','orders','order_items','payments','refunds'] LOOP
    EXECUTE format('CREATE TABLE dq_lab.%I (LIKE oltp.%I)', t, t);
  END LOOP;
END $$;
ALTER TABLE dq_lab.categories  ADD PRIMARY KEY (category_id);
ALTER TABLE dq_lab.regions     ADD PRIMARY KEY (region_id);
ALTER TABLE dq_lab.customers   ADD PRIMARY KEY (customer_id);
ALTER TABLE dq_lab.products    ADD PRIMARY KEY (product_id);
ALTER TABLE dq_lab.orders      ADD PRIMARY KEY (order_id);
ALTER TABLE dq_lab.order_items ADD PRIMARY KEY (order_item_id);
ALTER TABLE dq_lab.payments    ADD PRIMARY KEY (payment_id);
ALTER TABLE dq_lab.refunds     ADD PRIMARY KEY (refund_id);
