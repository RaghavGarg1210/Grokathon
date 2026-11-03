"""County Crier Streamlit entry point. Run: streamlit run app/streamlit_app.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="County Crier", page_icon=":loudspeaker:", layout="wide")

navigation = st.navigation(
    [
        st.Page("views/radar.py", title="Mayor Radar", icon=":material/radar:", default=True),
        st.Page("views/briefing.py", title="Briefing", icon=":material/article:"),
        st.Page("views/studio.py", title="Video Studio", icon=":material/movie:"),
        st.Page("views/library.py", title="Approved Library", icon=":material/video_library:"),
    ]
)
navigation.run()
