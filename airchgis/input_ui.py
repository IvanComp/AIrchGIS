"""Shared Streamlit input: upload files, or point to files already on this computer."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from airchgis.data_input import save_upload


def render_file_input(label, exts, key, subdir, multiple=True, help=None):
    """Upload the user's files. Returns a list of local paths (copies saved in the workspace)."""
    paths = []
    files = st.file_uploader(label, type=sorted(e.lstrip(".") for e in exts), accept_multiple_files=multiple,
                             key=f"{key}_upload", help=help)
    remembered = f"_as_uploaded_{key}"
    if files:
        files = files if isinstance(files, list) else [files]
        saved = [str(save_upload(f.name, f.getvalue(), subdir)) for f in files]
        st.session_state[remembered] = saved
        paths.extend(saved)
    elif st.session_state.get(remembered):
        # the uploader forgets its files when another screen is shown; keep using the saved copies
        kept = [p for p in st.session_state[remembered] if Path(p).exists()]
        if kept:
            st.caption("Still loaded: " + ", ".join(Path(p).name for p in kept))
            if st.button("Remove", key=f"{key}_forget"):
                st.session_state[remembered] = []
                st.rerun()
            paths.extend(kept)
    return [Path(p) for p in paths]
