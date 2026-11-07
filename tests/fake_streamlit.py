"""A small stand-in for `streamlit` so the pages can be executed headlessly (real Streamlit is not
installed in the build sandbox).  Widgets return their defaults unless a test overrides them:

    OVERRIDES[key_prefix_or_label] = value     # widget value
    PRESS.add(label_or_key_prefix)             # one-shot button press
    COMPONENT_VALUES[component_name] = value   # value returned by a custom component
"""
import contextlib
import sys
import types

OVERRIDES, PRESS, COMPONENT_VALUES = {}, set(), {}
CALLS = []            # (kind, payload) of everything rendered
MESSAGES = []         # (level, text)
DOWNLOADS = []


class Rerun(BaseException):   # like Streamlit's RerunException (not an Exception)
    pass


class State(dict):
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)

    def __setattr__(self, k, v):
        self[k] = v


session_state = State()


def _lookup(key, label):
    for src in (key, label):
        if src is None:
            continue
        best = None
        for pref in OVERRIDES:
            if str(src).startswith(pref) and (best is None or len(pref) > len(best)):
                best = pref
        if best is not None:
            return True, OVERRIDES[best]
    return False, None


def _value(label, key, default):
    hit, v = _lookup(key, label)
    if hit:
        if key:
            session_state[key] = v
        return v
    if key:
        if key in session_state:
            return session_state[key]
        session_state[key] = default
    return default


class Ctx:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):          # st.sidebar.x / col.x delegate to the module
        return getattr(sys.modules["streamlit"], name)


def columns(spec, **kw):
    n = spec if isinstance(spec, int) else len(spec)
    return [Ctx() for _ in range(n)]


def tabs(labels):
    return [Ctx() for _ in labels]


def expander(label, expanded=False):
    return Ctx()


def container(**kw):
    return Ctx()


@contextlib.contextmanager
def spinner(text=""):
    yield


def _msg(level):
    def f(text="", *a, **k):
        MESSAGES.append((level, str(text)))
    return f


def button(label, key=None, type=None, disabled=False, on_click=None, args=(), kwargs=None, **kw):
    if disabled:
        return False
    for tag in (key, label):
        if tag is None:
            continue
        for pref in list(PRESS):
            if str(tag).startswith(pref):
                PRESS.discard(pref)
                if on_click:
                    on_click(*args, **(kwargs or {}))
                return True
    return False


def download_button(label, data, file_name=None, mime=None, key=None, **kw):
    DOWNLOADS.append((label, file_name, len(data)))
    return False


def text_input(label, value="", key=None, **kw):
    return _value(label, key, value)


text_area = text_input


def number_input(label, min_value=None, max_value=None, value=None, step=None, key=None, **kw):
    v = _value(label, key, value if value is not None else (min_value or 0))
    return v


def selectbox(label, options, index=0, key=None, format_func=None, **kw):
    options = list(options)
    v = _value(label, key, options[index] if options and index is not None and index < len(options) else (options[0] if options else None))
    return v


def multiselect(label, options, default=None, key=None, **kw):
    return list(_value(label, key, list(default) if default is not None else []))


def radio(label, options, index=0, key=None, horizontal=False, **kw):
    options = list(options)
    return _value(label, key, options[index])


def slider(label, min_value=None, max_value=None, value=None, step=None, key=None, **kw):
    return _value(label, key, value if value is not None else min_value)


def checkbox(label, value=False, key=None, **kw):
    return _value(label, key, value)


def file_uploader(label, type=None, accept_multiple_files=False, key=None, **kw):
    hit, v = _lookup(key, label)
    if hit:
        return v
    return [] if accept_multiple_files else None


def data_editor(df, **kw):
    hit, v = _lookup(kw.get("key"), None)
    return v if hit else df


def _plain(level):
    def f(*a, **k):
        CALLS.append((level, a[:1]))
    return f


class _Bar:
    def progress(self, *a, **k):
        pass


def progress(v=0.0, **k):
    return _Bar()


def rerun():
    raise Rerun()


def set_page_config(**kw):
    pass


class ColumnConfig:
    def __getattr__(self, name):
        return lambda *a, **k: dict(kind=name, args=a, **k)


def declare_component(name, path=None, url=None):
    def call(*args, default=None, key=None, **kwargs):
        CALLS.append(("component:" + name, dict(key=key, **kwargs)))
        return COMPONENT_VALUES.get(name, default)
    return call


def install():
    st = types.ModuleType("streamlit")
    for n, f in dict(columns=columns, progress=progress, tabs=tabs, expander=expander, container=container, spinner=spinner,
                     button=button, download_button=download_button, text_input=text_input, text_area=text_area, number_input=number_input,
                     selectbox=selectbox, multiselect=multiselect, radio=radio, slider=slider, checkbox=checkbox,
                     file_uploader=file_uploader, data_editor=data_editor, rerun=rerun, set_page_config=set_page_config,
                     error=_msg("error"), warning=_msg("warning"), success=_msg("success"), info=_msg("info")).items():
        setattr(st, n, f)
    for n in ("markdown", "caption", "write", "subheader", "header", "title", "divider", "code", "text", "dataframe", "table",
              "metric", "json", "plotly_chart"):
        setattr(st, n, _plain(n))
    st.session_state = session_state
    st.sidebar = Ctx()
    st.column_config = ColumnConfig()
    comp = types.ModuleType("streamlit.components")
    v1 = types.ModuleType("streamlit.components.v1")
    v1.declare_component = declare_component
    comp.v1 = v1
    st.components = comp
    sys.modules.update({"streamlit": st, "streamlit.components": comp, "streamlit.components.v1": v1})
    return st


def run(render, max_reruns=6):
    """Execute a page function like Streamlit would, following st.rerun()."""
    for _ in range(max_reruns):
        try:
            render()
            return
        except Rerun:
            continue
    raise RuntimeError("rerun loop")
