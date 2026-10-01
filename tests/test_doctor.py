"""`framewall doctor`: a one-command check of whether this machine's tesseract
install can actually do OCR, so a bad language pack shows up before a scan
silently degrades. All faked here (no real tesseract needed) - the real
install is exercised by conftest.py's requires_tesseract-gated tests."""

from __future__ import annotations

from framewall import cli
from framewall import ocr as ocr_mod


def test_missing_binary_reports_not_on_path(monkeypatch, capsys):
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: None)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 1
    assert "not found on PATH" in out


def test_installed_but_nonfunctional_reports_the_same_condition_as_conftest(monkeypatch, capsys):
    # This is the exact failure mode this dev box hit: tesseract on PATH,
    # language data missing, scans silently degrading to heuristic-only.
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_mod, "tesseract_version", lambda: "tesseract 5.3.4")
    monkeypatch.setattr(ocr_mod, "list_languages", lambda: ["osd"])
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda lang=None: False)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 1
    assert ocr_mod.NO_LANGUAGE_DATA_REASON in out
    from tests.conftest import requires_tesseract

    # conftest's skip reason is worded identically to what doctor prints.
    assert requires_tesseract.kwargs["reason"] in out


def test_functional_install_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_mod, "tesseract_version", lambda: "tesseract 5.3.4")
    monkeypatch.setattr(ocr_mod, "list_languages", lambda: ["eng", "osd"])
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda lang=None: True)
    code = cli.main(["doctor"])
    out = capsys.readouterr().out
    assert code == 0
    assert "working" in out
    assert "eng, osd" in out


def test_lang_flag_reaches_diagnose(monkeypatch, capsys):
    seen = {}

    def fake_diagnose(lang=None):
        seen["lang"] = lang
        from framewall.ocr import Diagnosis

        return Diagnosis(
            path="/usr/bin/tesseract", version="tesseract 5.3.4", languages=["deu"],
            lang_requested=lang, functional=True, reason=None,
        )

    monkeypatch.setattr(cli, "diagnose", fake_diagnose)
    cli.main(["doctor", "--lang", "deu"])
    assert seen["lang"] == "deu"


def test_lang_env_var_is_honored(monkeypatch, capsys):
    seen = {}

    def fake_diagnose(lang=None):
        seen["lang"] = lang
        from framewall.ocr import Diagnosis

        return Diagnosis(
            path="/usr/bin/tesseract", version="tesseract 5.3.4", languages=["deu"],
            lang_requested=lang, functional=True, reason=None,
        )

    monkeypatch.setattr(cli, "diagnose", fake_diagnose)
    monkeypatch.setenv("FRAMEWALL_TESSERACT_LANG", "deu")
    cli.main(["doctor"])
    assert seen["lang"] == "deu"


def _broken_install(monkeypatch):
    monkeypatch.setattr(ocr_mod, "tesseract_path", lambda: "/usr/bin/tesseract")
    monkeypatch.setattr(ocr_mod, "tesseract_version", lambda: "tesseract 5.3.4")
    monkeypatch.setattr(ocr_mod, "list_languages", lambda: ["osd"])
    monkeypatch.setattr(ocr_mod, "ocr_functional", lambda lang=None: False)


def test_fix_line_names_the_requested_pack_for_each_package_manager(monkeypatch, capsys):
    _broken_install(monkeypatch)
    cli.main(["doctor", "--lang", "deu"])
    fix = [line for line in capsys.readouterr().out.splitlines() if line.startswith("fix:")]
    assert len(fix) == 1
    for hint in ("apt install tesseract-ocr-deu", "pacman -S tesseract-data-deu",
                 "brew install tesseract-lang"):
        assert hint in fix[0]
    assert "-eng" not in fix[0]


def test_fix_line_defaults_to_english(monkeypatch, capsys):
    _broken_install(monkeypatch)
    cli.main(["doctor"])
    out = capsys.readouterr().out
    assert "apt install tesseract-ocr-eng" in out
    assert "brew install tesseract\n" in out or out.rstrip().endswith("brew install tesseract")
