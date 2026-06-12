import streamlit as st
import pandas as pd

st.title("Budget AI Dashboard")

uploaded_file = st.file_uploader("Upload Budget CSV", type=["csv"])
if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.write(df.head())
    st.write("Columns:", df.columns.tolist())

    if st.button("Validate"):
        st.success("Validation completed. Add your validation logic.")

    if st.button("Run Forecast"):
        st.info("Forecasting is not yet connected.")
