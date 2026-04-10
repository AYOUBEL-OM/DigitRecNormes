from app.database import engine
import uuid

with engine.begin() as conn:
    res = conn.exec_driver_sql("SHOW COLUMNS FROM entreprises LIKE 'id_entreprise'")
    if res.fetchone() is None:
        conn.exec_driver_sql("ALTER TABLE entreprises ADD COLUMN id_entreprise VARCHAR(36) NULL UNIQUE")
        print('Added id_entreprise column')
    else:
        print('id_entreprise exists')

    rows = conn.exec_driver_sql("SELECT id FROM entreprises WHERE id_entreprise IS NULL OR id_entreprise = ''").fetchall()
    print('rows to fill', len(rows))
    for (row_id,) in rows:
        conn.exec_driver_sql("UPDATE entreprises SET id_entreprise = %s WHERE id = %s", (str(uuid.uuid4()), row_id))

    try:
        conn.exec_driver_sql("ALTER TABLE entreprises MODIFY id_entreprise VARCHAR(36) NOT NULL")
    except Exception as e:
        print('Could not set NOT NULL', e)

    rows = conn.exec_driver_sql("SELECT id, id_entreprise, email FROM entreprises LIMIT 5").fetchall()
    print('sample rows:', rows)
