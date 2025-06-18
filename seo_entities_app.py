import os
import streamlit as st

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

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
import re

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

def highlight_entities(text, entities):
    # Unique, longer names first to avoid partial highlight overlap
    entity_names = sorted({e["name"] for e in entities if e["name"].strip()}, key=len, reverse=True)
    def replacer(match):
        matched = match.group(0)
        return f'<mark style="background: #ffe066; color: #303030; padding:0 2px; border-radius:4px;">{matched}</mark>'
    for name in entity_names:
        # Word boundary only if name is a word; this makes it robust for phrases too
        if len(name) > 2:
            text = re.sub(r'(?i)\b{}\b'.format(re.escape(name)), replacer, text)
    return text

st.markdown("# SEO Entity Extraction Tool")
st.markdown("Analyse visible page or text content and see entities highlighted in your actual content.")

mode = st.radio("Select Input Mode", ["By URL", "Paste HTML", "Paste Plain Text"])
input_val = None
content_text = ""
entities = []
visible = ""

if mode == "By URL":
    url = st.text_input("Enter URL to fetch:")
    if st.button("Analyse"):
        with st.spinner("Fetching and analysing..."):
            try:
                response = requests.get(url)
                html = response.text
                visible = extract_visible_text(html)
                content_text = visible
                entities = get_entities(visible)
            except Exception as e:
                st.error(f"Error: {e}")

elif mode == "Paste HTML":
    html = st.text_area("Paste HTML here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted HTML..."):
            try:
                visible = extract_visible_text(html)
                content_text = visible
                entities = get_entities(visible)
            except Exception as e:
                st.error(f"Error: {e}")

else:
    text = st.text_area("Paste plain text here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted plain text..."):
            try:
                content_text = text
                entities = get_entities(text)
            except Exception as e:
                st.error(f"Error: {e}")

if entities:
    st.markdown("### Entities")
    st.dataframe(entities, use_container_width=True)
    st.download_button("Download Entities as JSON", json.dumps(entities, indent=2), file_name="entities.json")
    st.markdown("### Content with Entities Highlighted")
    highlighted = highlight_entities(content_text, entities)
    st.markdown(
        f'<div style="background: #faf9f6; padding:1em 1.2em; border-radius:6px; font-size: 1.1em;">{highlighted}</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")
st.caption("Entities are highlighted in yellow. This tool analyses only visible body content (not nav/footers/scripts). EngineRoom 2024.")
