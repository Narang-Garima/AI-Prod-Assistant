import os
import streamlit as st
from prod_assistant.etl.data_ingestion_working import DataIngestion

st.set_page_config(page_title="CSV → AstraDB Vector DB", page_icon="🧠", layout="centered")
st.title("🧠 CSV → AstraDB Vector DB (Test Ingestion + Retriever)")

st.markdown("Use this to ingest an existing CSV into AstraDB and test retrieval. No scraping.")

DEFAULT_CSV_PATH = "data/product_reviews.csv"

with st.expander("✅ Step 1: Provide CSV", expanded=True):
    mode = st.radio("Choose input method:", ["Use existing path", "Upload CSV"], horizontal=True)

    csv_path = None

    if mode == "Use existing path":
        csv_path = st.text_input("CSV path on disk:", value=DEFAULT_CSV_PATH)
        if csv_path and not os.path.exists(csv_path):
            st.warning(f"File not found at: {csv_path}")

    else:
        uploaded = st.file_uploader("Upload CSV file", type=["csv"])
        if uploaded is not None:
            os.makedirs("data", exist_ok=True)
            csv_path = os.path.join("data", uploaded.name)
            with open(csv_path, "wb") as f:
                f.write(uploaded.getbuffer())
            st.success(f"Uploaded and saved to: {csv_path}")

st.divider()

with st.expander("✅ Step 2: Ingest into AstraDB", expanded=True):
    if st.button("🚀 Ingest CSV to AstraDB", disabled=not (csv_path and os.path.exists(csv_path))):
        with st.spinner("📡 Initializing ingestion pipeline..."):
            try:
                ingestion = DataIngestion(csv_path=csv_path)  # <— important
                st.info("Running ingestion...")
                ingestion.run_pipeline()
                st.success("✅ Ingested successfully into AstraDB!")

                # Keep ingestion object for retriever testing
                st.session_state["ingestion_ready"] = True
                st.session_state["csv_path"] = csv_path
            except Exception as e:
                st.error("❌ Ingestion failed!")
                st.exception(e)

st.divider()

with st.expander("✅ Step 3: Test Retriever", expanded=True):
    query = st.text_input("Ask something to retrieve relevant reviews:", value="camera quality and battery")

    top_k = st.slider("Top K results", 1, 10, 4)

    if st.button("🔎 Run Retrieval", disabled=not st.session_state.get("ingestion_ready", False)):
        with st.spinner("Searching..."):
            try:
                # Recreate ingestion to get the same vector store/retriever
                ingestion = DataIngestion(csv_path=st.session_state["csv_path"])
                retriever = ingestion.get_retriever(k=top_k)  # <— implement this in DataIngestion

                docs = retriever.get_relevant_documents(query)

                if not docs:
                    st.warning("No results found.")
                else:
                    st.success(f"Found {len(docs)} results:")
                    for i, d in enumerate(docs, 1):
                        st.markdown(f"### Result {i}")
                        st.write(d.page_content)
                        if getattr(d, "metadata", None):
                            st.caption(d.metadata)

            except Exception as e:
                st.error("❌ Retrieval failed!")
                st.exception(e)