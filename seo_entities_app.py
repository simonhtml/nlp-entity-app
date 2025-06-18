import streamlit as st
import os
import json
import re
import html

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

# --- rerun compatible with all Streamlit versions
try:
    rerun = st.rerun
except AttributeError:
    rerun = st.experimental_rerun

# ---- Password + Login Button, Wide Centre Column ----
col1, col2, col3 = st.columns([1, 5, 1])  # Wide centre
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    with col2:
        st.markdown("### Login")
        pw = st.text_input("Password", type="password", key="pw_input")
        login = st.button("Login")
        if login:
            if pw == st.secrets["app_password"]:
                st.session_state["authenticated"] = True
                rerun()
            else:
                st.error("Incorrect password.")
        st.stop()

# ---- Rate Limiting ----
LIMIT = 15  # Number of analyses per user session
if "request_count" not in st.session_state:
    st.session_state["request_count"] = 0
if st.session_state["request_count"] >= LIMIT:
    st.error("Rate limit exceeded. Please wait or reload the app later.")
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
import pandas as pd
from io import StringIO

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
    ent_map = {}
    for ent in entities:
        ent_map[ent["name"]] = {
            "type": ent["type"],
            "relevance": ent["relevance"]
        }
    entity_list = sorted(ent_map.items(), key=lambda x: -len(x[0]))
    text = html.escape(text)
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
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                }
                response = requests.get(url, headers=headers)
                html_code = response.text
                content_text = extract_visible_text(html_code)
                entities, (category_path, category_conf) = get_entities_and_category(content_text)
                st.session_state["request_count"] += 1
            except Exception as e:
                st.error(f"Error: {e}")

elif mode == "Paste HTML":
    html_input = st.text_area("Paste HTML here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted HTML..."):
            try:
                content_text = extract_visible_text(html_input)
                entities, (category_path, category_conf) = get_entities_and_category(content_text)
                st.session_state["request_count"] += 1
            except Exception as e:
                st.error(f"Error: {e}")

else:
    text_input = st.text_area("Paste plain text here", height=150)
    if st.button("Analyse"):
        with st.spinner("Analysing pasted plain text..."):
            try:
                content_text = text_input
                entities, (category_path, category_conf) = get_entities_and_category(content_text)
                st.session_state["request_count"] += 1
            except Exception as e:
                st.error(f"Error: {e}")

# --- CATEGORY ---
if category_path and category_conf is not None:
    st.markdown(f"#### From your description, Google attributes this category to this entity")
    st.markdown(
        f'''
        <div style="display:flex;align-items:center;">
            <span style="color:#567;font-size:1.08em;">{' › '.join(category_path)}</span>
            <div style="background:#e3fbe3; border-radius:6px; margin-left:20px; height:20px; width:150px; display:inline-block; overflow:hidden;">
                <div style="background:#38b000; width:{category_conf}%; height:100%;"></div>
            </div>
            <span style="color:#38b000; margin-left:10px;">{category_conf}%</span>
        </div>
        ''',
        unsafe_allow_html=True
    )

# --- ENTITIES TABLE & DOWNLOAD ---
if entities:
    df = pd.DataFrame(entities)
    df = df.sort_values("salience", ascending=False)

    def make_progress_html(percent, colour):
        return f'''
        <div style="background:#f0f0f0;border-radius:4px;width:100%;height:18px;position:relative;">
            <div style="background:{colour};width:{percent}%;height:100%;border-radius:4px;"></div>
            <span style="position:absolute;top:0;left:50%;transform:translateX(-50%);font-size:0.85em;color:#222;">{percent}%</span>
        </div>'''

    rows = []
    for _, row in df.iterrows():
        colour = ENTITY_TYPE_COLOURS.get(row["type"], "#eee")
        relevance_bar = make_progress_html(row["relevance"], colour)
        wiki = row["wikipedia_url"]
        fallback_url = f"https://en.wikipedia.org/wiki/{row['name'].replace(' ', '_')}"
        if not wiki:
            wiki = fallback_url
            wiki_note = " (guessed)"
        else:
            wiki_note = ""
        wiki_link = f'<a href="{wiki}" target="_blank" rel="noopener">{wiki_note or "Wiki"}</a>'
        rows.append({
            "Entity": html.escape(row["name"]),
            "Type": row["type"],
            "Relevance": relevance_bar,
            "Wikipedia": wiki_link
        })

    # Custom table with progress bars and links
    st.markdown("### Entities (sorted by importance to topic)")
    st.markdown(
        '<table style="width:100%;">'
        '<tr><th align="left">Entity</th><th align="left">Type</th><th align="left">Relevance</th><th align="left">Wikipedia</th></tr>' +
        "".join(
            f'<tr>'
            f'<td>{r["Entity"]}</td>'
            f'<td>{r["Type"]}</td>'
            f'<td style="min-width:180px;">{r["Relevance"]}</td>'
            f'<td>{r["Wikipedia"]}</td>'
            f'</tr>'
            for r in rows
        ) +
        '</table>',
        unsafe_allow_html=True
    )

    # CSV download (using fallback for wiki)
    csv_buffer = StringIO()
    pd.DataFrame([
        {
            "Entity": r["Entity"],
            "Type": r["Type"],
            "Wikipedia": r["Wikipedia"]
        }
        for r in rows
    ]).to_csv(csv_buffer, index=False)
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
st.caption("Entities are highlighted with badges by type. Relevance = Google salience as percent. Topic category is shown above. Rate limited to 15 analyses per session. EngineRoom 2024.")
