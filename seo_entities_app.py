import streamlit as st
import os
import json
import re
import html
import requests
import pandas as pd
from io import StringIO
import colorsys

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

# --- Rerun compatibility for all Streamlit versions
try:
    rerun = st.rerun
except AttributeError:
    rerun = st.experimental_rerun

# ---- Password + Login Button, Wide Centre Column ----
col1, col2, col3 = st.columns([1, 5, 1])
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
LIMIT = 15
if "request_count" not in st.session_state:
    st.session_state["request_count"] = 0
if st.session_state["request_count"] >= LIMIT:
    st.error("Rate limit exceeded. Please wait or reload the app later.")
    st.stop()

# ---- Service Account ----
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

ENTITY_TYPE_COLOURS = {
    "PERSON": "#b7e4c7", "LOCATION": "#ffe066", "ORGANIZATION": "#a5d8ff",
    "EVENT": "#eebefa", "WORK_OF_ART": "#ffd6a5", "CONSUMER_GOOD": "#f4bfbf",
    "OTHER": "#cfd8dc", "ADDRESS": "#b2f0e3", "DATE": "#ffe6b3",
    "NUMBER": "#dee2e6", "PRICE": "#ffe0e0", "PHONE_NUMBER": "#e0f7fa",
    "ORGANISATION": "#a5d8ff", "CARDINAL": "#eeeec7", "ORDINAL": "#eeeec7"
}

def hex_to_rgb(hex_colour):
    hex_colour = hex_colour.lstrip("#")
    return tuple(int(hex_colour[i:i+2], 16) for i in (0, 2, 4))

def rgb_to_hex(rgb_tuple):
    return "#{:02x}{:02x}{:02x}".format(*rgb_tuple)

def adjust_lightness(hex_colour, amount=1.2):
    r, g, b = hex_to_rgb(hex_colour)
    h, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)
    l = max(0, min(1, l * amount))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex((int(r2*255), int(g2*255), int(b2*255)))

def adjust_darkness(hex_colour, amount=0.8):
    r, g, b = hex_to_rgb(hex_colour)
    h, l, s = colorsys.rgb_to_hls(r/255, g/255, b/255)
    l = max(0, min(1, l * amount))
    r2, g2, b2 = colorsys.hls_to_rgb(h, l, s)
    return rgb_to_hex((int(r2*255), int(g2*255), int(b2*255)))

def make_progress_html(percent, colour):
    light = adjust_lightness(colour, 1.7)
    dark = adjust_darkness(colour, 0.7)
    return f'''
    <div style="background:{light};border-radius:7px;width:105px;height:18px;position:relative;overflow:hidden;">
        <div style="background:{dark};width:{percent}%;height:100%;border-radius:7px 0 0 7px;"></div>
        <span style="position:absolute;top:0;left:50%;transform:translateX(-50%,0);font-size:0.95em;color:#222;font-weight:600;line-height:18px;">{percent}%</span>
    </div>'''

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
    try:
        category_resp = client.classify_text(document=doc)
        if category_resp.categories:
            top_cat = max(category_resp.categories, key=lambda c: c.confidence)
            category_breadcrumb = top_cat.name.split("/")
            confidence = round(top_cat.confidence * 100)
            return entities, (category_breadcrumb[1:], confidence)
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
st.markdown(
    """
    This tool analyses the visible content of a page or pasted text and extracts Google's identified entities, sorted by their importance to your topic ("relevance" from Google salience).  
    - Entities are shown with a progress bar for relevance and a Wikipedia link (if available).
    - A green progress bar above shows the confidence Google has in the overall topic classification.
    - "Google Wiki" means Google's Knowledge Graph mapped it directly.  
    - "No Google Wiki, guessed Wiki" tries to match the entity's Wikipedia page (if found).
    """
)

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
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}
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

# --- CATEGORY (with green progress bar) ---
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
    df = df.reset_index(drop=True)

    rows = []
    for idx, row in df.iterrows():
        colour = ENTITY_TYPE_COLOURS.get(row["type"], "#eee")
        relevance_bar = make_progress_html(row["relevance"], colour)
        # Wiki logic (fast version, no API calls)
        wiki = row["wikipedia_url"]
        entity_name = row["name"]
        if wiki:
            wiki_disp = f'Google Wiki: <a href="{wiki}" target="_blank" rel="noopener">{entity_name}</a>'
        else:
            guessed_url = f"https://en.wikipedia.org/wiki/{entity_name.replace(' ', '_')}"
            wiki_disp = f'No Google Wiki, guessed Wiki: <a href="{guessed_url}" target="_blank" rel="noopener">{entity_name}</a>'
        rows.append({
            "Entity": html.escape(entity_name),
            "Type": row["type"],
            "Relevance": relevance_bar,
            "Wikipedia": wiki_disp
        })

    # Only show top 20, expander for more
    TOP_N = 20
    shown = rows[:TOP_N]
    extra = rows[TOP_N:]

    def table_html(rows):
        return (
            '<table style="width:100%; font-size:0.98em; border-collapse:collapse;">'
            '<tr><th align="left">Entity</th><th align="left">Type</th><th align="left" style="width:115px;">Relevance</th><th align="left" style="width:320px;">Wikipedia</th></tr>' +
            "".join(
                f'<tr>'
                f'<td style="padding:3px 6px;">{r["Entity"]}</td>'
                f'<td style="padding:3px 6px;">{r["Type"]}</td>'
                f'<td style="padding:3px 6px;">{r["Relevance"]}</td>'
                f'<td style="padding:3px 6px;">{r["Wikipedia"]}</td>'
                f'</tr>'
                for r in rows
            ) +
            '</table>'
        )

    st.markdown("### Entities (sorted by importance to topic)")
    st.markdown(table_html(shown), unsafe_allow_html=True)
    if extra:
        with st.expander(f"Show {len(extra)} more entities"):
            st.markdown(table_html(extra), unsafe_allow_html=True)

    # CSV download
    csv_buffer = StringIO()
    pd.DataFrame([
        {
            "Entity": r["Entity"],
            "Type": r["Type"],
            "Wikipedia": re.sub("<.*?>", "", r["Wikipedia"])
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
st.caption("© Simon 2025")
