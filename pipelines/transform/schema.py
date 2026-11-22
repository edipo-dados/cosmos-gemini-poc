"""DDL do DuckDB analítico: 4 dimensões e 4 fatos. Valores monetários em DECIMAL(12,2)."""

DDL = [
    """CREATE TABLE dim_region (region_id INTEGER PRIMARY KEY, region_name VARCHAR NOT NULL, states VARCHAR)""",
    """CREATE TABLE dim_customer (
        customer_id INTEGER PRIMARY KEY, customer_name VARCHAR, email VARCHAR, segment VARCHAR,
        region_id INTEGER, region_name VARCHAR, city VARCHAR, state VARCHAR, created_at DATE)""",
    """CREATE TABLE dim_product (
        product_id INTEGER PRIMARY KEY, sku VARCHAR, product_name VARCHAR, category_id INTEGER,
        category_name VARCHAR, unit_price DECIMAL(12,2), is_active BOOLEAN)""",
    """CREATE TABLE dim_date (
        date_key DATE PRIMARY KEY, year INTEGER, quarter INTEGER, month INTEGER, year_month VARCHAR,
        month_start DATE, month_name_pt VARCHAR, day INTEGER, iso_weekday INTEGER, weekday_name_pt VARCHAR,
        is_weekend BOOLEAN)""",
    """CREATE TABLE fact_orders (
        order_id INTEGER PRIMARY KEY, customer_id INTEGER, region_id INTEGER, order_date DATE, status VARCHAR,
        is_paid BOOLEAN, total_amount DECIMAL(12,2), payment_method VARCHAR, payment_status VARCHAR)""",
    """CREATE TABLE fact_order_items (
        order_item_id INTEGER PRIMARY KEY, order_id INTEGER, product_id INTEGER, category_id INTEGER,
        order_date DATE, quantity INTEGER, unit_price DECIMAL(12,2), line_total DECIMAL(12,2))""",
    """CREATE TABLE fact_payments (
        payment_id INTEGER PRIMARY KEY, order_id INTEGER, method VARCHAR, status VARCHAR,
        amount DECIMAL(12,2), paid_at DATE)""",
    """CREATE TABLE fact_refunds (
        refund_id INTEGER PRIMARY KEY, order_item_id INTEGER, order_id INTEGER, product_id INTEGER,
        order_date DATE, refund_amount DECIMAL(12,2), status VARCHAR, refunded_at DATE, reason VARCHAR)""",
    """CREATE TABLE etl_meta (etl_run_id BIGINT, finished_at TIMESTAMP, source_row_counts JSON)""",
]

TABLES = ["dim_customer", "dim_product", "dim_region", "dim_date",
          "fact_orders", "fact_order_items", "fact_payments", "fact_refunds"]
