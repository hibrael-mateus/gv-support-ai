from app.agents.sql import correction_script, discovery_script, guard_sql, referenced_tables, unconfirmed_objects
from app.security import classify_sql


def test_discovery_is_read_only_and_uses_catalog():
    s = discovery_script("nota diario")
    assert "INFORMATION_SCHEMA.COLUMNS" in s.code and "sys.objects" in s.code and "sys.foreign_keys" in s.code
    assert not classify_sql(s.code).dangerous


def test_discovery_escapes_quotes_and_wildcards():
    s = discovery_script("o'brien_x")
    assert "o''brien[_]x" in s.code


def test_correction_follows_four_steps_with_transaction():
    s = correction_script("dbo.Exemplo", "id = 10", "ativo = 0")
    code = s.code
    assert s.dangerous and "UPDATE" in " ".join(s.reasons)
    order = [code.index(x) for x in ("SELECT COUNT(*)", "SELECT *", "BEGIN TRANSACTION", "UPDATE dbo.Exemplo", "-- COMMIT;")]
    assert order == sorted(order)
    assert "\nCOMMIT;" not in code  # never committed automatically


def test_danger_ignores_comments_and_strings():
    assert not classify_sql("-- DELETE FROM x\nSELECT 'UPDATE' AS t").dangerous
    assert classify_sql("DELETE FROM x WHERE id=1").dangerous


def test_invented_tables_are_flagged_and_discovery_prepended():
    sql = "SELECT * FROM dbo.TabelaInventada t JOIN sys.objects o ON 1=1"
    assert referenced_tables(sql) == ["dbo.TabelaInventada", "sys.objects"]
    assert unconfirmed_objects(sql, "nenhuma evidencia") == ["dbo.TabelaInventada"]
    scripts = guard_sql(sql, "")
    assert scripts[0].title.startswith("Descoberta") and scripts[1].warnings


def test_known_tables_from_evidence_are_accepted():
    assert unconfirmed_objects("SELECT * FROM dbo.Matricula", "resultado: dbo.matricula 120 linhas") == []


def test_dangerous_llm_sql_is_wrapped_in_transaction():
    scripts = guard_sql("UPDATE dbo.Matricula SET x=1 WHERE id=2", "dbo.matricula")
    assert "BEGIN TRANSACTION" in scripts[-1].code and "-- COMMIT;" in scripts[-1].code
