"""冷记忆/画像术语抽取与清洗：泛化词、虚词碎片、LaTeX 残留、词库整词抑制（2026-08-11 修复）。"""
from app.services.graph import lexicon as _lexicon
from app.services.graph.terms import extract_profile_terms, sanitize_profile_term_freq


def test_extract_profile_terms_filters_generic_and_stopchars(monkeypatch):
    monkeypatch.setattr(_lexicon, "load_domain_lexicon", lambda: (frozenset(), frozenset()))
    text = "定义是理论的基石，的稳德的证明，变分法研究泛函极值"
    terms = extract_profile_terms(text, 30)
    for bad in ("定义", "理论", "的稳", "德的", "证明"):
        assert bad not in terms
    assert "变分" in terms
    assert "泛函" in terms


def test_extract_profile_terms_drops_latex_commands(monkeypatch):
    monkeypatch.setattr(_lexicon, "load_domain_lexicon", lambda: (frozenset(), frozenset()))
    text = r"测度空间上的积分为 \int f \, d\mu，其中 \mathrm{span} 与 \frac{1}{2} 相关"
    terms = extract_profile_terms(text, 30)
    for bad in ("mathrm", "frac", "int", "mu", "span"):
        assert bad not in terms
    assert "测度" in terms
    assert "积分" in terms


def test_extract_profile_terms_lexicon_whole_word_suppresses_fragments(monkeypatch):
    monkeypatch.setattr(
        _lexicon, "load_domain_lexicon", lambda: (frozenset({"线性代数", "泛函分析"}), frozenset())
    )
    text = "线性代数与泛函分析的核心是线性映射与范数理论"
    terms = extract_profile_terms(text, 30)
    assert "线性代数" in terms
    assert "泛函分析" in terms
    assert "性代" not in terms
    assert "线性" not in terms
    assert "代数" not in terms


def test_sanitize_profile_term_freq_cleans_legacy_data(monkeypatch):
    monkeypatch.setattr(_lexicon, "load_domain_lexicon", lambda: (frozenset(), frozenset()))
    legacy = {
        "定义": 515.0,
        "任意": 234.0,
        "函数": 410.0,
        "的稳": 22.0,
        "德的": 22.0,
        "与名": 22.0,
        "mathrm": 20.0,
        "frac": 20.0,
        "Hilbert": 5.0,
        "Banach": 3.0,
    }
    cleaned = sanitize_profile_term_freq(legacy)
    for bad in ("定义", "任意", "的稳", "德的", "与名", "mathrm", "frac"):
        assert bad not in cleaned
    assert "Hilbert" in cleaned
    assert "Banach" in cleaned
    assert "函数" in cleaned  # 数学核心术语不属于泛化词
