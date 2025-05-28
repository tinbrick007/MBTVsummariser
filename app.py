import os
import json
import time
import urllib.parse

import streamlit as st
import yt_dlp
import requests
import browser_cookie3
import pandas as pd

# === CONFIGURATION ===
SUBSCRIPTION_KEY = os.getenv("AZURE_SUBSCRIPTION_KEY")
LOCATION         = os.getenv("AZURE_LOCATION", "trial")
ACCOUNT_ID       = os.getenv("AZURE_ACCOUNT_ID")

for var in ("AZURE_SUBSCRIPTION_KEY","AZURE_ACCOUNT_ID"):
    if not os.getenv(var):
        st.error(f"Missing environment variable: {var}")
        st.stop()




os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# === FUNCTIONS ===

def download_youtube_video(youtube_url: str) -> str:
    ydl_opts = {
        "format": "mp4",
        "outtmpl": os.path.join(DOWNLOAD_FOLDER, "%(title)s.%(ext)s"),
        "merge_output_format": "mp4",
        "cookiesfrombrowser": ("chrome",),
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        return ydl.prepare_filename(info)

@st.cache(show_spinner=False)
def get_account_access_token() -> str:
    auth_url = (
        f"https://api.videoindexer.ai/Auth/{LOCATION}"
        f"/Accounts/{ACCOUNT_ID}/AccessToken?allowEdit=true"
    )
    headers = {"Ocp-Apim-Subscription-Key": SUBSCRIPTION_KEY}
    resp = requests.get(auth_url, headers=headers)
    resp.raise_for_status()
    return resp.text.strip('"')

@st.cache(show_spinner=False)
def upload_video_file(file_path: str, access_token: str) -> str:
    upload_url = (
        f"https://api.videoindexer.ai/{LOCATION}"
        f"/Accounts/{ACCOUNT_ID}/Videos?accessToken={access_token}"
        f"&name={urllib.parse.quote(VIDEO_NAME)}"
        f"&privacy=Private&language={LANGUAGE}"
    )
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f)}
        resp = requests.post(upload_url, files=files)
    resp.raise_for_status()
    return resp.json()["id"]

def wait_for_indexing(video_id: str, access_token: str):
    status_url = (
        f"https://api.videoindexer.ai/{LOCATION}"
        f"/Accounts/{ACCOUNT_ID}/Videos/{video_id}/Index?accessToken={access_token}"
    )
    while True:
        resp = requests.get(status_url)
        resp.raise_for_status()
        if resp.json().get("state") == "Processed":
            break
        time.sleep(5)

@st.cache(show_spinner=False)
def fetch_insights(video_id: str, access_token: str) -> dict:
    insights_url = (
        f"https://api.videoindexer.ai/{LOCATION}"
        f"/Accounts/{ACCOUNT_ID}/Videos/{video_id}/Index?accessToken={access_token}"
    )
    resp = requests.get(insights_url)
    resp.raise_for_status()
    return resp.json()

# === STREAMLIT UI ===
st.set_page_config(page_title="Video Insights", layout="wide")
st.title("Azure Video Indexer Insights")

# Input
col1, col2 = st.columns([3,1])
youtube_url = col1.text_input("YouTube Video URL:")
if col2.button("Analyze Video"):
    if not youtube_url:
        st.error("Enter a valid YouTube URL.")
    else:
        # Process
        with st.spinner("Downloading video..."):
            local_file = download_youtube_video(youtube_url)
        st.success(f"Downloaded: {local_file}")

        with st.spinner("Authenticating..." ):
            token = get_account_access_token()
        st.success("Token acquired....")

        with st.spinner("Uploading..." ):
            vid = upload_video_file(local_file, token)
        st.success("Video uploaded.")

        with st.spinner("Indexing..." ):
            wait_for_indexing(vid, token)
        st.success("Indexing complete!")

        with st.spinner("Fetching insights..." ):
            insights = fetch_insights(vid, token)
        st.success("Insights fetched.")

        # Prepare dataframes
        def build_df(items, key_name):
            rows = []
            for item in items:
                textInfo = item.get(key_name) if key_name != 'text' else item.get('text')
                conf = item.get('confidence')
                inst_list = item.get('instances', [])
                for inst in inst_list:
                    rows.append({
                        "Text": textInfo,
                        "Confidence": round(conf,3),
                        "Start": inst.get('start'),
                        "End": inst.get('end')
                    })
            return pd.DataFrame(rows)

        df_ocr    = build_df(insights.get('videos', []).get('Ocr', []), 'text')
        df_kw     = build_df(insights.get('keywords', []), 'text')
        df_topics = build_df(insights.get('topics', []), 'name')

        # Tabs for sections
        tab1, tab2, tab3, tab4 = st.tabs(["OCR", "Keywords", "Topics", "Raw JSON"])

        with tab1:
            st.markdown("**OCR Extracted Text**")
            st.write(f"Total items: {len(df_ocr)}")
            st.dataframe(df_ocr, use_container_width=True)

        with tab2:
            st.markdown("**Keywords**")
            st.write(f"Total keywords: {len(df_kw)}")
            st.dataframe(df_kw, use_container_width=True)

        with tab3:
            st.markdown("**Topics**")
            st.write(f"Total topics: {len(df_topics)}")
            st.dataframe(df_topics, use_container_width=True)

        with tab4:
            st.markdown("**Raw Insights JSON**")
            st.download_button(
                label="Download JSON",
                data=json.dumps(insights, indent=2),
                file_name=OUTPUT_FILE,
                mime="application/json",
                key="download-json"
            )
