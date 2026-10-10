import json

from app.agents import GVSupportOrchestrator
from app.agents.rtm import describe, lint, parse_rtm
from app.extract import extract_pages

CODE = """procedure varMediaOnCalc(var Value: Variant);
begin
  Value := plNotas['SOMA_NOTAS'] / plNotas['QTD_AVALIACOES'];
end;"""


def _prop(name: str, value: bytes) -> bytes:
    return bytes([len(name)]) + name.encode() + value


def _short(s: str) -> bytes:
    return b"\x06" + bytes([len(s)]) + s.encode("cp1252")


def program_stream(source: str) -> bytes:
    """A TraCodeModule.ProgramStream with one event, encoded the way Delphi writes it."""
    long = source.encode("cp1252")
    return (b"\x01" + _short("TraEventHandler")[1:]
            + _prop("ProgramName", _short("varMediaOnCalc"))
            + _prop("ProgramType", b"\x07\x0bttProcedure")
            + _prop("Source", b"\x0c" + len(long).to_bytes(4, "little") + long)
            + _prop("ComponentName", _short("varMedia"))
            + _prop("EventName", _short("OnCalc"))
            + _prop("EventID", b"\x02\x21") + b"\x00\x00")


def text_rtm(source: str = CODE) -> bytes:
    hexed = program_stream(source).hex().upper()
    lines = "\n".join("      " + hexed[i:i + 64] for i in range(0, len(hexed), 64))
    return f"""object ppReport1: TppReport
  object ppDetailBand1: TppDetailBand
    object ppDBText1: TppDBText
      DataField = 'NOME_ALUNO'
      DataPipeline = plNotas
    end
    object varMedia: TppVariable
      DataType = dtDouble
    end
  end
  object daSQL1: TdaSQL
    UserName = 'plNotas'
    SQLText.Strings = (
      'SELECT A.NOME AS NOME_ALUNO, SUM(N.NOTA) AS SOMA_NOTAS,'
      '  COUNT(N.ID) AS QTD_AVALIACOES'
      'FROM ALUNOS A JOIN NOTAS N ON N.ALUNO = A.ID GROUP BY A.NOME')
  end
  object raCodeModule1: TraCodeModule
    ProgramStream = {{
{lines}}}
  end
end
""".encode("cp1252")


def test_reads_components_sql_and_the_rap_code_hidden_in_program_stream():
    r = parse_rtm(text_rtm())
    assert r["programs"][0]["source"] == CODE and r["programs"][0]["event"] == "OnCalc"
    assert "QTD_AVALIACOES" in r["sql"][0]
    text = describe("boletim.rtm", text_rtm())
    assert "varMedia.OnCalc" in text and "DataField=NOME_ALUNO" in text
    assert extract_pages("boletim.rtm", text_rtm())[0][1] == text  # indexed and attached the same way


def test_binary_rtm_code_is_found_too():
    binary = b"TPF0\x09TppReport\x0appReport1" + b"\x00" * 10 + program_stream(CODE)
    assert parse_rtm(binary)["programs"][0]["source"] == CODE


def test_lint_finds_division_by_zero_nulls_unknown_fields_and_unclosed_blocks():
    issues = lint(describe("r.rtm", text_rtm()))
    assert any("divisão" in i for i in issues) and any("nulo" in i for i in issues)
    assert not any("não aparece" in i for i in issues)  # both fields exist in the SQL
    broken = "procedure X(var Value: Variant);\nbegin\n  if plNotas['MEDIA_FINAL'] > 7 then begin\n    Value := 1;\nend;"
    issues = lint(broken + "\nSELECT NOTA FROM T")
    assert any("não fechado" in i for i in issues) and any("MEDIA_FINAL" in i for i in issues)
    assert any("sem 'Value" in i for i in lint("procedure V(var Value: Variant);\nbegin\nend;"))


class OneReply:
    name = "one"

    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def status(self):
        return {"online": True, "models": ["x"], "model": "x"}

    def list_models(self):
        return ["x"]

    def chat(self, messages, json_mode=False):
        self.prompts.append(messages)
        return json.dumps(self.reply)

    def embed(self, texts):
        return None


def test_chat_routes_an_rtm_to_the_rtm_agent_with_checks_and_corrected_code():
    fixed = "procedure varMediaOnCalc(var Value: Variant);\nbegin\n  Value := 0;\nend;"
    llm = OneReply({"analysis": "A média divide por QTD_AVALIACOES, que é zero sem avaliações.",
                    "fixes": [{"event": "varMediaOnCalc", "code": fixed}], "steps": "Aba Calc > varMedia > OnCalc."})
    msg = "o boletim dá Division by zero\n\n[Arquivo: boletim.rtm]\n" + describe("boletim.rtm", text_rtm())
    out = GVSupportOrchestrator(llm).chat(msg)["message"]
    assert out["agent"] == "RTMAgent"
    assert "```pascal" in out["content"] and "divisão por plNotas['QTD_AVALIACOES']" in out["content"]
    assert CODE in llm.prompts[0][-1]["content"]  # the model saw the decoded RAP code
