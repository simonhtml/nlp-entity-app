import streamlit as st
import os
import json
import re
import html

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

# --- Secure Password ---
if "authenticated" not in st.session_state:
    password = st.text_input("Password", type="password")
    if password == st.secrets["app_password"]:
        st.session_state["authenticated"] = True
        st.experimental_rerun()
    else:
        st.stop()

# --- Service Account Setup ---
CREDENTIALS_PATH = "google_credentials.json"
if not os.path.exists(CREDENTIALS_PATH):
    creds = st.secrets["SEO_TEAM_461800"]
    # Fix double-escaping for private_key in TOML
    if "\\n" in creds and "\n" not in creds:
        creds = creds.replace("\\n", "\n")
    with open(CREDENTIALS_PATH, "w") as f:
        f.write(creds)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH

from bs4 import BeautifulSoup
from google.cloud import language_v1

def extract_visible_text(html_code):
    soup = BeautifulSoup(html_code, "html.parser")
    for tag in soup(["script", "style", "head", "title", "meta", "[document]", "noscript"]):
        tag.decompose()
    for tag in soup.find_all(['nav', 'footer', 'aside']):
        tag.decompose()
    for tag in soup.find_all(attrs={'class': ['sidebar', 'nav', 'footer', 'menu', 'header']}):
        tag.decompose()
    for tag in soup.find_all(attrs={'id': ['sidebar', 'nav', 'footer', 'menu', 'header']}):
        tag.decompose()
    return soup.body.get_text(separator=' ', strip=True) if soup.body else soup.get_text(separator=' ', strip=True)

def get_entities_with_salience(text):
    client = language_v1.LanguageServiceClient()
    document = language_v1.Document(content=text, type_=language_v1.Document.Type.PLAIN_TEXT)
    response = client.analyze_entities(document=document, encoding_type='UTF8')
    entities = []
    for e in response.entities:
        entities.append({
            "name": e.name,
            "type": language_v1.Entity.Type(e.type_).name,
            "salience": float(round(e.salience, 3)),
            "wikipedia_url": str(e.metadata.get("wikipedia_url", "")),
            "mid": str(e.metadata.get("mid", "")),
        })
    return entities

def highlight_entities_spacy_style(text, entities):
    entity_list = sorted(
        set((e["name"], e["type"], e["salience"]) for e in entities if e["name"].strip()),
        key=lambda x: -len(x[0])
    )
    text = html.escape(text)
    for name, etype, salience in entity_list:
        opacity = min(0.45 + salience, 1.0)
        badge = (
            f'<span style="background:rgba(255, 235, 59, {opacity}); color:#222; border-radius:4px; '
            f'padding:2px 6px 2px 4px; margin:1px; font-size:0.97em; font-family:monospace;" '
            f'title="Salience: {salience}">{html.escape(name)}'
            f' <span style="background:#fffbe7; color:#7b7800; border-radius:2px; font-size:0.73em; padding:0 5px 0 5px; margin-left:4px;">{etype}</span>'
            f'</span>'
        )
        text = re.sub(r'(?i)(?<![>\w])' + re.escape(name) + r'(?!</span>)', badge, text)
    return text

st.markdown("# SEO Entity Extraction Tool")
st.markdown("Analyse visible page or text content and see entities (with salience) highlighted in your content.")

mode = st.radio("Select Input Mode", ["By URL", "Paste HTML", "Paste Plain Text"])
entities = []
content_text = ""

if mode == "By URL":
    url = st.text_input("Enter URL to fetch:")
    if st.button("Analyse"):
        with st.spinner("Fetching and analysing..."):
            try:
                import requests
                response = requests.get(url)
                html_code = response.text
                content_text = extract_visible_text(html_code)
                entities = get_entities_with_salience(content_text)
            except Exception as e:
                st.error(f"Error: {e}")

elif mode == "Paste HTML":
    html_input = st.text_area("Paste HTML here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted HTML..."):
            try:
                content_text = extract_visible_text(html_input)
                entities = get_entities_with_salience(content_text)
            except Exception as e:
                st.error(f"Error: {e}")

else:
    text_input = st.text_area("Paste plain text here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted plain text..."):
            try:
                content_text = text_input
                entities = get_entities_with_salience(content_text)
            except Exception as e:
                st.error(f"Error: {e}")

if entities:
    import pandas as pd
    df = pd.DataFrame(entities)
    df = df.sort_values("salience", ascending=False)
    st.markdown("### Entities (sorted by importance to topic)")
    st.dataframe(df, use_container_width=True)
    # Robust download: always valid JSON, no missing fields
    download_entities = [{k: str(v) for k, v in entity.items()} for entity in entities]
    st.download_button("Download Entities as JSON", json.dumps(download_entities, indent=2), file_name="entities.json")
    st.markdown("### Content with Entities Highlighted")
    styled_content = highlight_entities_spacy_style(content_text, entities)
    st.markdown(
        f'<div style="background: #fafbff; padding:1em 1.2em; border-radius:8px; line-height:1.85;">{styled_content}</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")
st.caption("Entities are highlighted in yellow. Importance is measured by salience. Tool analyses only visible content. EngineRoom 2024.")
