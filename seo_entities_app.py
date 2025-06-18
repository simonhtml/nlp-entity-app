import streamlit as st
import requests
import json
import re
import html

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

# --- PULL SECRETS ---
API_KEY = st.secrets.get("NLP_API_KEY")
AUTH_PASSWORD = st.secrets.get("APP_PASSWORD")
# Service account (for reference, not used here):
# SERVICE_ACCOUNT = st.secrets.get("SEO_TEAM_461800")

# --- PASSWORD PROTECTION ---
if "authenticated" not in st.session_state:
    password = st.text_input("Password", type="password")
    if password != AUTH_PASSWORD:
        st.stop()
    else:
        st.session_state["authenticated"] = True

def extract_visible_text(html_code):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_code, "html.parser")
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

def get_entities_via_api_key(text, api_key):
    url = f"https://language.googleapis.com/v1/documents:analyzeEntities?key={api_key}"
    payload = {
        "document": {
            "type": "PLAIN_TEXT",
            "content": text
        },
        "encodingType": "UTF8"
    }
    r = requests.post(url, json=payload)
    result = r.json()
    if "error" in result:
        raise RuntimeError(result["error"].get("message", "API Error"))
    entities = []
    for e in result.get("entities", []):
        entities.append({
            "name": e.get("name"),
            "type": e.get("type"),
            "salience": round(e.get("salience", 3), 3),
            "wikipedia_url": e.get("metadata", {}).get("wikipedia_url", ""),
            "mid": e.get("metadata", {}).get("mid", "")
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
                response = requests.get(url)
                html_code = response.text
                content_text = extract_visible_text(html_code)
                entities = get_entities_via_api_key(content_text, API_KEY)
            except Exception as e:
                st.error(f"Error: {e}")

elif mode == "Paste HTML":
    html_input = st.text_area("Paste HTML here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted HTML..."):
            try:
                content_text = extract_visible_text(html_input)
                entities = get_entities_via_api_key(content_text, API_KEY)
            except Exception as e:
                st.error(f"Error: {e}")

else:
    text_input = st.text_area("Paste plain text here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted plain text..."):
            try:
                content_text = text_input
                entities = get_entities_via_api_key(content_text, API_KEY)
            except Exception as e:
                st.error(f"Error: {e}")

if entities:
    import pandas as pd
    df = pd.DataFrame(entities)
    df = df.sort_values("salience", ascending=False)
    st.markdown("### Entities (sorted by importance to topic)")
    st.dataframe(df, use_container_width=True)
    st.download_button("Download Entities as JSON", df.to_json(orient="records", indent=2), file_name="entities.json")
    st.markdown("### Content with Entities Highlighted")
    styled_content = highlight_entities_spacy_style(content_text, entities)
    st.markdown(
        f'<div style="background: #fafbff; padding:1em 1.2em; border-radius:8px; line-height:1.85;">{styled_content}</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")
st.caption("Entities are highlighted in yellow. Importance is measured by salience. Tool analyses only visible content. EngineRoom 2024.")
