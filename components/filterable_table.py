import streamlit as st
import pandas as pd

_filter_counter = {"n": 0}


def render_filterable_dataframe(df, key_prefix="ft", height=None):
    """Render a dataframe with per-column dropdown filters.
    Filters appear as a row of multiselects above the table.
    """
    if df.empty:
        st.info("No data.")
        return df

    _filter_counter["n"] += 1
    k = f"{key_prefix}_{_filter_counter['n']}"

    filtered = df.copy()

    # Let user pick which columns to filter
    with st.expander("Column filters", expanded=False):
        all_cols = df.columns.tolist()
        chosen_cols = st.multiselect(
            "Select columns to filter",
            options=all_cols,
            default=None,
            placeholder="Choose columns...",
            key=f"{k}_pick",
        )

        if chosen_cols:
            # Render a filter for each chosen column
            n_cols = min(len(chosen_cols), 4)
            rows_of_filters = [chosen_cols[i:i + n_cols] for i in range(0, len(chosen_cols), n_cols)]

            for row_cols in rows_of_filters:
                cols = st.columns(len(row_cols))
                for col_widget, col_name in zip(cols, row_cols):
                    with col_widget:
                        unique_vals = filtered[col_name].dropna().astype(str).unique()
                        unique_vals = sorted(set(unique_vals))

                        if len(unique_vals) <= 500:
                            selected = st.multiselect(
                                col_name,
                                options=unique_vals,
                                default=None,
                                placeholder=f"All...",
                                key=f"{k}_{col_name}",
                            )
                            if selected:
                                filtered = filtered[filtered[col_name].astype(str).isin(selected)]
                        else:
                            search = st.text_input(
                                col_name,
                                placeholder=f"Search...",
                                key=f"{k}_{col_name}",
                            )
                            if search and search.strip():
                                filtered = filtered[
                                    filtered[col_name].astype(str).str.contains(search.strip(), case=False, na=False)
                                ]

    st.caption(f"{len(filtered):,} of {len(df):,} rows")
    kwargs = {"use_container_width": True, "hide_index": True}
    if height:
        kwargs["height"] = height
    st.dataframe(filtered.reset_index(drop=True), **kwargs)

    return filtered
