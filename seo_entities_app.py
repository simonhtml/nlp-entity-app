import streamlit as st
import os
import requests
from bs4 import BeautifulSoup
import json
from google.cloud import language_v1

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "google_credentials.json"

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
    visible_text = soup.body.get_text(separator=' ', strip=True) if soup.body else soup.get_text(separator=' ', strip=True)
    return visible_text

def get_entities(text):
    client = language_v1.LanguageServiceClient()
    document = language_v1.Document(content=text, type_=language_v1.Document.Type.PLAIN_TEXT)
    response = client.analyze_entities(document=document, encoding_type='UTF8')
    entities = [{"name": e.name, "type": language_v1.Entity.Type(e.type_).name} for e in response.entities]
    return entities

st.set_page_config(page_title="SEO Body Entity Extractor", layout="wide")

if "authenticated" not in st.session_state:
    password = st.text_input("Password", type="password")
    if password == st.secrets["app_password"]:
        st.session_state["authenticated"] = True
        st.experimental_rerun()
    else:
        st.stop()

st.title("SEO Body Content Entity Extractor")

url = st.text_input("Enter the URL to check", "")
if st.button("Extract Entities") and url:
    with st.spinner("Fetching and analysing..."):
        try:
            response = requests.get(url)
            visible_text = extract_visible_text(response.text)
            entities = get_entities(visible_text)
            st.subheader("Extracted Entities from Visible Body Text")
            st.table(entities)
            st.download_button("Download Entities as JSON", json.dumps(entities, indent=2), file_name="entities.json")
            with st.expander("Show extracted visible text"):
                st.text_area("Visible text", visible_text, height=200)
        except Exception as e:
            st.error(f"Error: {e}")
