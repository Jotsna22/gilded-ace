"""The Gilded Ace floor decision dashboard."""

import streamlit as st

from gilded.ui import render

st.set_page_config(
    page_title="The Gilded Ace",
    page_icon="♠",
    layout="wide",
    initial_sidebar_state="expanded",
)
render()
