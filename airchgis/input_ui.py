"""Shared Streamlit input: upload files, or point to files already on this computer."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from airchgis.data_input import resolve_local_paths, save_upload


def render_file_input(label, exts, key, subdir, multiple=True, help=None):
    """Two ways in, upload first. Returns a list of local paths."""
    up_tab, path_tab = st.tabs(["Upload your files", "Use files already on this computer"])
    paths = []
    with up_tab:
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
    with path_tab:
        text = st.text_area("Paths (one per line; a folder loads every file inside)", key=f"{key}_paths", height=80,
                            help="No copy is made: useful for very large files.")
        local = resolve_local_paths(text, exts=set(exts))
        if text.strip() and not local:
            st.warning("No matching file found at these paths.")
        paths.extend(local)
    return [Path(p) for p in paths]
