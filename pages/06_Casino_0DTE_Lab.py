from __future__ import annotations

import streamlit as st
from src.ui.casino_page import render_casino_page

st.set_page_config(page_title="Christiania — Casino", page_icon="🎲", layout="wide")
render_casino_page()
