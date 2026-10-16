"""Offline execution harness for app.py (no Streamlit server, no browser).

It substitutes a minimal fake ``streamlit`` (and, when not installed, plotly / pyproj) so the whole
page logic in app.py really executes: every code path up to widget rendering, button handlers
(``clicks``) and widget values (``overrides``). It catches NameError/KeyError/TypeError regressions
in page code. It does NOT check layout, styling, browser behaviour or real Streamlit semantics -
those still need a live run (``streamlit run app.py``) as required by the project checklist.
"""
import runpy, sys, types, datetime, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Stop(Exception): pass
class _Rerun(Exception): pass


class _State(dict):
    def __getattr__(self, k):
        try: return self[k]
        except KeyError: raise AttributeError(k)
    def __setattr__(self, k, v): self[k] = v


class _Ctx:
    def __init__(self, st): self._st = st
    def __enter__(self): return self._st
    def __exit__(self, *a): return False
    def __getattr__(self, name): return getattr(self._st, name)


class FakeSt(types.ModuleType):
    def __init__(self, state=None, overrides=None, clicks=None):
        super().__init__('streamlit')
        self.session_state = _State(state or {})
        self.overrides = overrides or {}; self.clicks = set(clicks or [])
        self.messages = {'error': [], 'warning': [], 'success': [], 'info': []}
        self.rendered_buttons = []
        self.sidebar = _Ctx(self)

    def _ov(self, key, label, default):
        for k in (key, label):
            if k is not None and k in self.overrides: return self.overrides[k]
        return default

    # ---- layout
    def set_page_config(self, *a, **k): pass
    def columns(self, spec, **k):
        n = spec if isinstance(spec, int) else len(spec); return [_Ctx(self) for _ in range(n)]
    def expander(self, *a, **k): return _Ctx(self)
    def tabs(self, labels): return [_Ctx(self) for _ in labels]
    def container(self, *a, **k): return _Ctx(self)
    def stop(self): raise _Stop()
    def rerun(self): raise _Rerun()
    # ---- output
    def _msg(kind):
        def f(self, text='', *a, **k): self.messages[kind].append(str(text))
        return f
    error = _msg('error'); warning = _msg('warning'); success = _msg('success'); info = _msg('info')
    def markdown(self, *a, **k): pass
    def title(self, *a, **k): pass
    def caption(self, *a, **k): pass
    def write(self, *a, **k): pass
    def json(self, *a, **k): pass
    def code(self, *a, **k): pass
    def divider(self, *a, **k): pass
    def metric(self, *a, **k): pass
    def dataframe(self, *a, **k): pass
    def plotly_chart(self, *a, **k): pass
    # ---- input widgets (return the default / override)
    def button(self, label, *a, key=None, disabled=False, **k):
        self.rendered_buttons.append(label)
        return (label in self.clicks or key in self.clicks) and not disabled
    def download_button(self, *a, **k): return False
    def number_input(self, label, min_value=None, max_value=None, value=None, step=None, *a, key=None, **k):
        if value is None: value = min_value if min_value is not None else 0.0
        v = self._ov(key, label, value)
        if key is not None: self.session_state.setdefault(key, v)
        return v
    def text_input(self, label, value='', *a, key=None, **k): return self._ov(key, label, value)
    def text_area(self, label, value='', *a, key=None, **k): return self._ov(key, label, value)
    def checkbox(self, label, value=False, *a, key=None, **k): return self._ov(key, label, value)
    def selectbox(self, label, options, index=0, *a, key=None, **k):
        opts = list(options); default = opts[index] if opts and index is not None and index < len(opts) else None
        return self._ov(key, label, default)
    def radio(self, label, options, index=0, *a, key=None, **k):
        opts = list(options); return self._ov(key, label, opts[index] if opts else None)
    def multiselect(self, label, options, default=None, *a, key=None, **k): return self._ov(key, label, list(default or []))
    def file_uploader(self, *a, **k): return None
    def data_editor(self, df, *a, **k): return df
    def date_input(self, label, value=None, *a, **k): return value or datetime.date.today()


class _Fig:
    def __init__(self, *a, **k): self.traces = []
    def add_trace(self, t, *a, **k): self.traces.append(t)
    def to_html(self, *a, **k): return '<html></html>'
    def __getattr__(self, name): return lambda *a, **k: self


_STUBBED = []


def _install_optional_stubs():
    try: import plotly  # noqa
    except ImportError:
        _STUBBED.extend(['plotly', 'plotly.graph_objects', 'plotly.subplots'])
        go = types.ModuleType('plotly.graph_objects'); go.Figure = _Fig
        for n in ('Scatter', 'Scatter3d', 'Bar', 'Surface'): setattr(go, n, lambda *a, **k: dict(k))
        sub = types.ModuleType('plotly.subplots'); sub.make_subplots = lambda *a, **k: _Fig()
        pl = types.ModuleType('plotly'); pl.graph_objects = go; pl.subplots = sub
        sys.modules.update({'plotly': pl, 'plotly.graph_objects': go, 'plotly.subplots': sub})
    try: import pyproj  # noqa
    except ImportError:
        _STUBBED.extend(['pyproj', 'models.geodesy'])
        pp = types.ModuleType('pyproj')
        class CRS:
            def __init__(self, s): self.s = str(s); self.name = self.s; self.is_projected = '4326' not in self.s
            @classmethod
            def from_user_input(cls, s): return cls(s)
            def to_string(self): return self.s
        class Transformer:
            @classmethod
            def from_crs(cls, *a, **k): return cls()
            def transform(self, x, y, *a, **k): return x * 1.0, y * 1.0
        pp.CRS, pp.Transformer, pp.Proj = CRS, Transformer, lambda *a, **k: None
        sys.modules['pyproj'] = pp


def run_app(page='Dashboard', project=None, overrides=None, clicks=None, extra_state=None):
    """Execute app.py once. Returns the FakeSt (messages, session_state) and the exception raised, if any."""
    _install_optional_stubs()
    sys.path.insert(0, ROOT)
    state = {'active_page': page}
    if project is not None: state['project'] = project
    state.update(extra_state or {})
    fake = FakeSt(state, overrides, clicks)
    saved = sys.modules.get('streamlit'); sys.modules['streamlit'] = fake
    err = None
    try:
        runpy.run_path(os.path.join(ROOT, 'app.py'), run_name='__main__')
    except (_Stop, _Rerun):
        pass
    except Exception as ex:                       # noqa: BLE001 - the harness reports any page failure
        import traceback; err = ex; fake.traceback = traceback.format_exc()
    finally:
        if saved is None: sys.modules.pop('streamlit', None)
        else: sys.modules['streamlit'] = saved
        for name in _STUBBED: sys.modules.pop(name, None)     # never leak fake libraries into other tests
        _STUBBED.clear()
    return fake, err
