from __future__ import annotations

import streamlit as st

from src.dashboard.read_model import (
    load_command_deck,
)


st.set_page_config(
    page_title="Christiania",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _pct(value: int, target: int) -> float:
    if target <= 0:
        return 0.0
    return min(
        max(value / target, 0.0),
        1.0,
    )


def _none(value, fallback="—"):
    return (
        fallback
        if value is None
        else value
    )


def _status_label(value) -> str:
    return str(
        value or "UNKNOWN"
    ).replace("_", " ").title()


st.markdown(
    '''
    <style>
    .christiania-kicker {
        font-size: 0.78rem;
        letter-spacing: 0.22em;
        opacity: 0.72;
        margin-bottom: 0.2rem;
    }
    .christiania-title {
        font-size: 2.55rem;
        font-weight: 700;
        letter-spacing: 0.03em;
        margin-bottom: 0.2rem;
    }
    .christiania-subtitle {
        opacity: 0.78;
        margin-bottom: 1.2rem;
    }
    .governance-box {
        border: 1px solid rgba(190, 155, 88, 0.45);
        border-radius: 0.6rem;
        padding: 0.85rem 1rem;
        margin: 0.5rem 0 1rem 0;
    }
    </style>
    ''',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="christiania-kicker">'
    "V1 RESEARCH WORKSTATION"
    "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="christiania-title">'
    "CHRISTIANIA // COMMAND DECK"
    "</div>",
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="christiania-subtitle">'
    "Prospective options research, calibration, "
    "shadow structures and operational health."
    "</div>",
    unsafe_allow_html=True,
)

@st.cache_data(ttl=30)
def _load_snapshot():
    return load_command_deck()


snapshot = _load_snapshot()

with st.sidebar:
    st.header("Navigation")

    page = st.radio(
        "Deck",
        [
            "Command",
            "Prospective",
            "Observations",
            "Shadow Lab",
            "System",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    if st.button(
        "Refresh deck",
        use_container_width=True,
    ):
        st.cache_data.clear()
        st.rerun()

    st.caption(
        "Research-only V1. No broker-order path."
    )

if not snapshot["ready"]:
    st.error(
        "Christiania cannot open the research deck: "
        f"{snapshot['reason']}"
    )
    st.json(
        snapshot["database"]
    )
    st.stop()

database = snapshot["database"]
latest_iteration = snapshot[
    "latest_iteration"
]
latest_run = snapshot[
    "latest_run"
]
prospective = snapshot[
    "prospective"
]
counts = snapshot[
    "research_counts"
]

st.markdown(
    '''
    <div class="governance-box">
    <strong>Scientific state:</strong>
    prospective observation and calibration.
    Surfaced anomalies are observational evidence,
    not validated edge and not trade instructions.
    Decision, admission-by-model and live-order
    automation remain disabled.
    </div>
    ''',
    unsafe_allow_html=True,
)

if page == "Command":
    c1, c2, c3, c4 = st.columns(4)

    with c1:
        st.metric(
            "Latest daemon cycle",
            _status_label(
                latest_iteration[
                    "status"
                ]
                if latest_iteration
                else None
            ),
            (
                f"#{latest_iteration['id']}"
                if latest_iteration
                else None
            ),
        )

    with c2:
        st.metric(
            "Latest research run",
            _status_label(
                latest_run["status"]
                if latest_run
                else None
            ),
            (
                f"run {latest_run['id']}"
                if latest_run
                else None
            ),
        )

    with c3:
        st.metric(
            "Prospective dates",
            prospective[
                "independent_dates"
            ],
            "first review at 5",
        )

    with c4:
        st.metric(
            "Recovered samples",
            prospective[
                "recovered_samples"
            ],
            "queryable provenance",
        )

    st.subheader(
        "Prospective calibration"
    )

    st.write(
        "First descriptive review"
    )
    st.progress(
        _pct(
            prospective[
                "independent_dates"
            ],
            5,
        )
    )
    st.caption(
        f"{prospective['independent_dates']} / 5 "
        "independent prospective dates"
    )

    st.write(
        "Prereg-quality review threshold"
    )
    st.progress(
        _pct(
            prospective[
                "independent_dates"
            ],
            20,
        )
    )
    st.caption(
        f"{prospective['independent_dates']} / 20 "
        "independent prospective dates"
    )

    st.divider()

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Surfaced observations",
        counts["surfaced_total"],
    )
    c2.metric(
        "Defined-risk proposals",
        counts["proposals_total"],
    )
    c3.metric(
        "Shadow candidates",
        counts["shadow_candidates"],
    )
    c4.metric(
        "Shadow marks",
        counts["shadow_marks"],
    )

    st.subheader(
        "Recent daemon iterations"
    )

    if snapshot[
        "recent_iterations"
    ]:
        st.dataframe(
            snapshot[
                "recent_iterations"
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No daemon iterations recorded yet."
        )

elif page == "Prospective":
    st.subheader(
        "Prospective evidence"
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Observation rows",
        prospective[
            "observation_rows"
        ],
    )
    c2.metric(
        "Recovered rows",
        prospective[
            "recovered_rows"
        ],
    )
    c3.metric(
        "Prospective start",
        _none(
            prospective[
                "prospective_start_session_date"
            ]
        ),
    )

    st.subheader(
        "Frozen model registry"
    )
    st.dataframe(
        snapshot["models"],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader(
        "Prospective hypotheses"
    )
    st.dataframe(
        snapshot["hypotheses"],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader(
        "Recovery provenance"
    )

    if snapshot[
        "recovery_summary"
    ]:
        st.dataframe(
            snapshot[
                "recovery_summary"
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.success(
            "No recovered samples recorded."
        )

elif page == "Observations":
    st.subheader(
        "Recent surfaced observations"
    )
    st.caption(
        "OBSERVATIONAL ONLY — these rows are "
        "not validated edge and are not trade signals."
    )

    if snapshot[
        "recent_anomalies"
    ]:
        st.dataframe(
            snapshot[
                "recent_anomalies"
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No surfaced observations recorded."
        )

elif page == "Shadow Lab":
    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Proposals",
        counts[
            "proposals_total"
        ],
        (
            f"{counts['proposals_blocked']} "
            "builder-blocked"
        ),
    )
    c2.metric(
        "Admitted shadows",
        counts[
            "admitted_total"
        ],
        (
            f"{counts['admission_blocked']} "
            "admission-blocked"
        ),
    )
    c3.metric(
        "Shadow candidates",
        counts[
            "shadow_candidates"
        ],
    )

    st.subheader(
        "Recent structure proposals"
    )

    if snapshot[
        "recent_proposals"
    ]:
        st.dataframe(
            snapshot[
                "recent_proposals"
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No structure proposals recorded."
        )

    st.subheader(
        "Recent shadow candidates"
    )

    if snapshot[
        "recent_candidates"
    ]:
        st.dataframe(
            snapshot[
                "recent_candidates"
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No shadow candidates recorded."
        )

elif page == "System":
    st.subheader(
        "Database health"
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Schema",
        f"v{database['schema_version']}",
    )
    c2.metric(
        "Journal mode",
        str(
            database[
                "journal_mode"
            ]
        ).upper(),
    )
    c3.metric(
        "Quick check",
        _status_label(
            database[
                "quick_check"
            ]
        ),
    )
    c4.metric(
        "FK violations",
        database[
            "foreign_key_violation_count"
        ],
    )

    st.code(
        database["path"],
        language=None,
    )

    st.subheader(
        "Daemon state"
    )

    if snapshot[
        "daemon_lock"
    ]:
        st.json(
            snapshot[
                "daemon_lock"
            ]
        )
    else:
        st.warning(
            "No active daemon lease is recorded."
        )

    st.subheader(
        "Latest research manifest"
    )

    if latest_run:
        st.json(
            latest_run
        )
    else:
        st.info(
            "No research runs recorded."
        )

    st.subheader(
        "Operational rules"
    )
    st.markdown(
        '''
        - SQLite remains the V1 operational database.
        - The dashboard opens the database read-only.
        - The research daemon remains the primary writer.
        - Online backups use SQLite's backup API and are
          integrity-checked before publication.
        - No database, API secret or broker credential is
          committed to Git.
        - No live broker-order path is present in this app.
        '''
    )
