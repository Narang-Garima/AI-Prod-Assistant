import importlib
import sys
import types
from pathlib import Path


class _DummySpinner:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _SessionState(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, key, value):
        self[key] = value


def _load_powerbi_module_with_streamlit_stub():
    st = types.ModuleType("streamlit")
    st.session_state = _SessionState()
    st.title = lambda *a, **k: None
    st.caption = lambda *a, **k: None
    st.subheader = lambda *a, **k: None
    st.text_area = lambda *a, **k: ""
    st.text_input = lambda *a, value="", **k: value
    st.button = lambda *a, **k: False
    st.number_input = lambda *a, value=0, **k: value
    st.info = lambda *a, **k: None
    st.success = lambda *a, **k: None
    st.warning = lambda *a, **k: None
    st.error = lambda *a, **k: None
    st.exception = lambda *a, **k: None
    st.write = lambda *a, **k: None
    st.download_button = lambda *a, **k: None
    st.spinner = lambda *a, **k: _DummySpinner()
    sys.modules["streamlit"] = st

    sys.modules.pop("scrape_buddy_powerbi", None)
    return importlib.import_module("scrape_buddy_powerbi")


def test_ensure_history_csv_creates_header(tmp_path: Path):
    mod = _load_powerbi_module_with_streamlit_stub()
    out = tmp_path / "history.csv"
    mod.ensure_history_csv(str(out))
    content = out.read_text(encoding="utf-8")
    assert "run_id" in content
    assert "product_title" in content


def test_append_history_rows_is_append_only(tmp_path: Path):
    mod = _load_powerbi_module_with_streamlit_stub()
    out = tmp_path / "history.csv"
    rows = [
        ["PID1", "Phone A", "4.5", "100", "10000", "good phone"],
        ["PID2", "Phone B", "4.2", "200", "12000", "nice battery"],
    ]
    count1 = mod.append_history_rows(str(out), rows, "phones", "run-1", "2026-01-01T00:00:00Z")
    count2 = mod.append_history_rows(str(out), rows[:1], "phones", "run-2", "2026-01-02T00:00:00Z")
    assert count1 == 2
    assert count2 == 1
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1 + 3
    assert "run-1" in lines[1]
    assert "run-2" in lines[-1]
