import os
import streamlit as st

st.set_page_config(page_title="SEO Entity Tool", layout="wide")  # MUST be first Streamlit command

# --- PASSWORD PROTECTION ---
if "authenticated" not in st.session_state:
    password = st.text_input("Password", type="password")
    if password != "EngineRoom2024!":
        st.stop()
    else:
        st.session_state["authenticated"] = True

# --- LOAD GOOGLE NLP CREDENTIALS FROM STREAMLIT SECRET ---
if "SEO_TEAM_461800" in st.secrets:
    with open("google_credentials.json", "w") as f:
        f.write(str(st.secrets["SEO_TEAM_461800"]))
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_credentials.json"

import requests
from bs4 import BeautifulSoup
from google.cloud import language_v1
import json

def extract_visible_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta", "[document]", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(['nav', 'footer', 'aside']):
        tag.decompose()
    for tag in soup.find_all(attrs={'class': ['sidebar', 'nav', 'footer', 'menu', 'header']}):
        tag.decompose()
    for tag in soup.find_all(attrs={'id': ['sidebar', 'nav', 'footer', 'menu', 'header']}):
        tag.decompose()
    if soup.body:
        return soup.body.get_text(separator=' ', strip=True)
    else:
        return soup.get_text(separator=' ', strip=True)

def get_entities(text):
    client = language_v1.LanguageServiceClient()
    document = language_v1.Document(content=text, type_=language_v1.Document.Type.PLAIN_TEXT)
    response = client.analyze_entities(document=document, encoding_type='UTF8')
    entities = [{"name": e.name, "type": language_v1.Entity.Type(e.type_).name} for e in response.entities]
    return entities

st.title("SEO Entity Extraction Tool (URL or Paste Mode)")

mode = st.radio("Select Input Mode", ["By URL", "Paste HTML", "Paste Plain Text"])

if mode == "By URL":
    url = st.text_input("Enter URL to fetch:")
    if st.button("Analyse URL"):
        with st.spinner("Fetching and analysing..."):
            try:
                response = requests.get(url)
                html = response.text
                visible = extract_visible_text(html)
                entities = get_entities(visible)
                st.success("Entities extracted from page body content.")
                st.write(entities)
                st.download_button("Download Entities as JSON", json.dumps(entities, indent=2), file_name="entities.json")
                with st.expander("Show extracted visible text"):
                    st.text_area("Visible text", visible, height=200)
            except Exception as e:
                st.error(f"Error: {e}")

elif mode == "Paste HTML":
    html = st.text_area("Paste HTML here")
    if st.button("Analyse HTML"):
        with st.spinner("Analysing pasted HTML..."):
            try:
                visible = extract_visible_text(html)
                entities = get_entities(visible)
                st.success("Entities extracted from pasted HTML body content.")
                st.write(entities)
                st.download_button("Download Entities as JSON", json.dumps(entities, indent=2), file_name="entities.json")
                with st.expander("Show extracted visible text"):
                    st.text_area("Visible text", visible, height=200)
            except Exception as e:
                st.error(f"Error: {e}")

else:
    text = st.text_area("Paste plain text here")
    if st.button("Analyse Text"):
        with st.spinner("Analysing pasted plain text..."):
            try:
                entities = get_entities(text)
                st.success("Entities extracted from pasted plain text.")
                st.write(entities)
                st.download_button("Download Entities as JSON", json.dumps(entities, indent=2), file_name="entities.json")
                with st.expander("Show input text"):
                    st.text_area("Input text", text, height=200)
            except Exception as e:
                st.error(f"Error: {e}")
