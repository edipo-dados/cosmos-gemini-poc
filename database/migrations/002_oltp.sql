-- Schema OLTP oficial: dados válidos, com PKs, FKs, CHECKs, UNIQUEs e índices.
CREATE TABLE oltp.categories (
    category_id integer PRIMARY KEY,
    name        text NOT NULL UNIQUE
);

CREATE TABLE oltp.regions (
    region_id integer PRIMARY KEY,
    name      text NOT NULL UNIQUE,
    states    text NOT NULL
);

CREATE TABLE oltp.customers (
    customer_id integer PRIMARY KEY,
    name        text NOT NULL,
    email       text NOT NULL UNIQUE,
    segment     text NOT NULL CHECK (segment IN ('Varejo','Premium','Corporativo','Pequena Empresa')),
    region_id   integer NOT NULL REFERENCES oltp.regions (region_id),
    city        text NOT NULL,
    state       char(2) NOT NULL,
    created_at  date NOT NULL
);
CREATE INDEX ix_customers_region ON oltp.customers (region_id);
CREATE INDEX ix_customers_segment ON oltp.customers (segment);

CREATE TABLE oltp.products (
    product_id  integer PRIMARY KEY,
    sku         text NOT NULL UNIQUE,
    name        text NOT NULL,
    category_id integer NOT NULL REFERENCES oltp.categories (category_id),
    unit_price  numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    is_active   boolean NOT NULL DEFAULT true
);
CREATE INDEX ix_products_category ON oltp.products (category_id);

CREATE TABLE oltp.orders (
    order_id     integer PRIMARY KEY,
    customer_id  integer NOT NULL REFERENCES oltp.customers (customer_id),
    order_date   date NOT NULL,
    status       text NOT NULL CHECK (status IN ('pending','paid','cancelled','refunded')),
    total_amount numeric(12,2) NOT NULL CHECK (total_amount >= 0)
);
CREATE INDEX ix_orders_customer ON oltp.orders (customer_id);
CREATE INDEX ix_orders_order_date ON oltp.orders (order_date);
CREATE INDEX ix_orders_status ON oltp.orders (status);

CREATE TABLE oltp.order_items (
    order_item_id integer PRIMARY KEY,
    order_id      integer NOT NULL REFERENCES oltp.orders (order_id),
    product_id    integer NOT NULL REFERENCES oltp.products (product_id),
    quantity      integer NOT NULL CHECK (quantity > 0),
    unit_price    numeric(12,2) NOT NULL CHECK (unit_price >= 0),
    line_total    numeric(12,2) NOT NULL CHECK (line_total >= 0),
    CONSTRAINT ck_items_line_total CHECK (line_total = quantity * unit_price)
);
CREATE INDEX ix_items_order ON oltp.order_items (order_id);
CREATE INDEX ix_items_product ON oltp.order_items (product_id);

CREATE TABLE oltp.payments (
    payment_id integer PRIMARY KEY,
    order_id   integer NOT NULL UNIQUE REFERENCES oltp.orders (order_id),
    method     text NOT NULL CHECK (method IN ('credit_card','debit_card','pix','boleto')),
    status     text NOT NULL CHECK (status IN ('captured','pending','voided')),
    amount     numeric(12,2) NOT NULL CHECK (amount >= 0),
    paid_at    date,
    CONSTRAINT ck_payments_paid_at CHECK ((status = 'captured') = (paid_at IS NOT NULL))
);
CREATE INDEX ix_payments_method ON oltp.payments (method);

CREATE TABLE oltp.refunds (
    refund_id     integer PRIMARY KEY,
    order_item_id integer NOT NULL UNIQUE REFERENCES oltp.order_items (order_item_id),
    refund_amount numeric(12,2) NOT NULL CHECK (refund_amount >= 0),
    status        text NOT NULL CHECK (status IN ('completed','pending','rejected')),
    refunded_at   date NOT NULL,
    reason        text
);
CREATE INDEX ix_refunds_status ON oltp.refunds (status);
-- Regra entre tabelas (reembolso <= valor do item/pago) não é expressável como CHECK:
-- é verificada pelas regras de qualidade (refund_exceeds_paid).
