import streamlit as st
import os
import json
import re
import html

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

# ---- Password protection ----
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    password = st.text_input("Password", type="password")
    if password == st.secrets["app_password"]:
        st.session_state["authenticated"] = True
        st.stop()
    else:
        st.stop()

# ---- Write service account JSON to file ----
CREDENTIALS_PATH = "google_credentials.json"
if not os.path.exists(CREDENTIALS_PATH):
    creds = st.secrets["SEO_TEAM_461800"]
    if "\\n" in creds and "\n" not in creds:
        creds = creds.replace("\\n", "\n")
    with open(CREDENTIALS_PATH, "w") as f:
        f.write(creds)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH

from bs4 import BeautifulSoup
from google.cloud import language_v1

# Pastel colour palette per entity type (Google NLP types)
ENTITY_TYPE_COLOURS = {
    "PERSON": "#b7e4c7",          # mint green
    "LOCATION": "#ffe066",        # yellow
    "ORGANIZATION": "#a5d8ff",    # sky blue
    "EVENT": "#eebefa",           # purple
    "WORK_OF_ART": "#ffd6a5",     # peach
    "CONSUMER_GOOD": "#f4bfbf",   # pink
    "OTHER": "#cfd8dc",           # grey-blue
    "ADDRESS": "#b2f0e3",         # teal
    "DATE": "#ffe6b3",            # pale orange
    "NUMBER": "#dee2e6",          # light grey
    "PRICE": "#ffe0e0",           # pale red
    "PHONE_NUMBER": "#e0f7fa",    # pale cyan
    "ORGANISATION": "#a5d8ff",    # fallback for UK/AU spelling
    "CARDINAL": "#eeeec7",        # light cream
    "ORDINAL": "#eeeec7"          # light cream
}

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

def get_entities_and_category(text):
    client = language_v1.LanguageServiceClient()
    # Entities
    doc = language_v1.Document(content=text, type_=language_v1.Document.Type.PLAIN_TEXT)
    entities_response = client.analyze_entities(document=doc, encoding_type='UTF8')
    entities = []
    for e in entities_response.entities:
        entities.append({
            "name": e.name,
            "type": language_v1.Entity.Type(e.type_).name,
            "salience": float(round(e.salience, 3)),
            "relevance": int(round(e.salience * 100)),
            "wikipedia_url": str(e.metadata.get("wikipedia_url", "")),
            "mid": str(e.metadata.get("mid", "")),
        })
    # Content Category (only works for >20 tokens, else returns empty list)
    try:
        category_resp = client.classify_text(document=doc)
        if category_resp.categories:
            top_cat = max(category_resp.categories, key=lambda c: c.confidence)
            category_breadcrumb = top_cat.name.split("/")
            confidence = round(top_cat.confidence * 100)
            return entities, (category_breadcrumb[1:], confidence)  # drop leading empty element
    except Exception:
        pass
    return entities, ([], None)

def highlight_entities_in_content(text, entities):
    if not text:
        return ""
    # Build map of entity -> (type, relevance)
    ent_map = {}
    for ent in entities:
        ent_map[ent["name"]] = {
            "type": ent["type"],
            "relevance": ent["relevance"]
        }
    # Sort by length descending for longest match first (avoid partial overlaps)
    entity_list = sorted(ent_map.items(), key=lambda x: -len(x[0]))
    text = html.escape(text)
    # Insert highlight spans for each entity
    for name, info in entity_list:
        if not name.strip():
            continue
        colour = ENTITY_TYPE_COLOURS.get(info["type"], "#e0e0e0")
        label = info["type"]
        sal = info["relevance"]
        badge = (
            f'<span style="background:{colour};color:#222;border-radius:4px;padding:2px 4px 2px 4px;margin:1px 1px 1px 0;'
            f'font-size:1em;display:inline-block;white-space:nowrap;" title="{label} | Relevance: {sal}%">'
            f'{html.escape(name)}'
            f'<span style="background:#222;color:#fff;border-radius:2px;font-size:0.75em;padding:1px 7px;margin-left:7px;margin-right:1px;">{label}</span>'
            f'</span>'
        )
        # Only highlight the first occurrence for each entity
        text = re.sub(r'(?<![>\w])' + re.escape(name) + r'(?!</span>)', badge, text, count=1)
    return text

# --- UI ---

st.markdown("# SEO Entity Extraction Tool")
st.markdown("Analyse visible content or text and see entities highlighted in your content with type badge and salience percent. Categories at top, full table, CSV download.")

mode = st.radio("Select Input Mode", ["By URL", "Paste HTML", "Paste Plain Text"])
entities = []
content_text = ""
category_path = []
category_conf = None

if mode == "By URL":
    url = st.text_input("Enter URL to fetch:")
    if st.button("Analyse"):
        with st.spinner("Fetching and analysing..."):
            try:
                import requests
                response = requests.get(url)
                html_code = response.text
                content_text = extract_visible_text(html_code)
                entities, (category_path, category_conf) = get_entities_and_category(content_text)
            except Exception as e:
                st.error(f"Error: {e}")

elif mode == "Paste HTML":
    html_input = st.text_area("Paste HTML here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted HTML..."):
            try:
                content_text = extract_visible_text(html_input)
                entities, (category_path, category_conf) = get_entities_and_category(content_text)
            except Exception as e:
                st.error(f"Error: {e}")

else:
    text_input = st.text_area("Paste plain text here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted plain text..."):
            try:
                content_text = text_input
                entities, (category_path, category_conf) = get_entities_and_category(content_text)
            except Exception as e:
                st.error(f"Error: {e}")

# --- CATEGORY ---
if category_path:
    cat_str = " › ".join(category_path)
    st.markdown(f"#### From your description, Google attributes this category to this entity")
    st.markdown(f'<span style="color:#567;">{" › ".join(category_path)}</span> <span style="color:#aaa;font-size:0.9em;">({category_conf}% confidence)</span>', unsafe_allow_html=True)

# --- ENTITIES TABLE & DOWNLOAD ---
if entities:
    import pandas as pd
    df = pd.DataFrame(entities)
    df = df.sort_values("salience", ascending=False)
    st.markdown("### Entities (sorted by importance to topic)")
    st.dataframe(df[["name", "type", "relevance", "wikipedia_url"]].rename(columns={"name":"Entity", "type":"Type", "relevance":"Relevance (%)", "wikipedia_url":"Wikipedia URL"}), use_container_width=True)
    # --- Robust CSV Download ---
    from io import StringIO
    csv_buffer = StringIO()
    df[["name", "type", "relevance", "wikipedia_url"]].to_csv(csv_buffer, index=False)
    st.download_button("Download Entities as CSV", csv_buffer.getvalue(), file_name="entities.csv", mime="text/csv")
    # --- Highlighted Content ---
    st.markdown("### Content with Entities Highlighted")
    styled_content = highlight_entities_in_content(content_text, entities)
    if styled_content.strip():
        st.markdown(
            f'<div style="background: #fafbff; padding:1em 1.2em; border-radius:8px; line-height:1.85;">{styled_content}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No content to highlight or no entities found.")

st.markdown("---")
st.caption("Entities are highlighted with badges by type. Relevance = Google salience as percent. Topic category is shown above. EngineRoom 2024.")
