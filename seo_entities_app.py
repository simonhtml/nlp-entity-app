import streamlit as st
import os
import re
import html
import requests
import pandas as pd
import unicodedata
from io import StringIO

st.set_page_config(page_title="SEO Entity Extraction", layout="wide")

try:
    rerun = st.rerun
except AttributeError:
    rerun = st.experimental_rerun

# ---- PASSWORD ----
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

# ---- RATE LIMIT ----
LIMIT = 15
if "request_count" not in st.session_state:
    st.session_state["request_count"] = 0
if st.session_state["request_count"] >= LIMIT:
    st.error("Rate limit exceeded. Please wait or reload the app later.")
    st.stop()

# ---- GOOGLE CREDENTIALS ----
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
    "PERSON": "#51cf66", "LOCATION": "#ffe066", "ORGANIZATION": "#339af0", "ORG": "#339af0",
    "EVENT": "#eebefa", "WORK_OF_ART": "#ffd6a5", "CONSUMER_GOOD": "#f4bfbf", "PRODUCT": "#f4bfbf",
    "OTHER": "#adb5bd", "ADDRESS": "#b2f0e3", "DATE": "#ffe6b3", "NUMBER": "#dee2e6",
    "PRICE": "#ffe0e0", "PHONE_NUMBER": "#e0f7fa", "CARDINAL": "#eeeec7", "ORDINAL": "#eeeec7"
}

SCHEMA_TYPE_MAP = {
    "PERSON": ["Person"],
    "ORG": ["Organization", "LocalBusiness"],
    "LOCATION": ["Place", "AdministrativeArea", "PostalAddress"],
    "EVENT": ["Event"],
    "WORK_OF_ART": ["CreativeWork"],
    "PRODUCT": ["Product"],
    "CONSUMER_GOOD": ["Product"],
    "DATE": ["Date"],
    "NUMBER": [],
    "PRICE": ["PriceSpecification"],
    "ADDRESS": ["PostalAddress"],
    "OTHER": [],
    "CARDINAL": [],
    "ORDINAL": []
}

def adjust_colour(hex_colour, light=True):
    hex_colour = hex_colour.lstrip("#")
    r, g, b = [int(hex_colour[i:i+2], 16) for i in (0, 2, 4)]
    if light:
        r = int((255 - r) * 0.7 + r)
        g = int((255 - g) * 0.7 + g)
        b = int((255 - b) * 0.7 + b)
    else:
        r = int(r * 0.85)
        g = int(g * 0.85)
        b = int(b * 0.85)
    return f"#{r:02x}{g:02x}{b:02x}"

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

def clean_entity_name(name):
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[‘’´`]", "'", name)
    name = re.sub(r'[“”]', '"', name)
    name = re.sub(r"[\u2013\u2014]", "-", name)
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.encode("ascii", "ignore").decode("ascii")
    return name.title()

def get_schema_links(entity_type, entity_name):
    schemas = SCHEMA_TYPE_MAP.get(entity_type, [])
    links = [f'<a href="https://schema.org/{s}" target="_blank" rel="noopener">{s}</a>' for s in schemas]
    return ", ".join(links) if links else ""

def count_occurrences(text, name):
    pattern = r"\b" + re.escape(name) + r"\b"
    return len(re.findall(pattern, text, flags=re.IGNORECASE))

def get_entities_and_category(text, progress=None):
    if progress: progress.progress(0.55, "Google NLP: extracting entities…")
    client = language_v1.LanguageServiceClient()
    doc = language_v1.Document(content=text, type_=language_v1.Document.Type.PLAIN_TEXT)
    entities_response = client.analyze_entities(document=doc, encoding_type='UTF8')
    entity_map = {}
    for e in entities_response.entities:
        name = clean_entity_name(e.name)
        if not name:
            continue
        etype = language_v1.Entity.Type(e.type_).name
        if etype == "ORGANIZATION":
            etype = "ORG"
        if name not in entity_map or e.salience > entity_map[name]["salience"]:
            entity_map[name] = {
                "name": name,
                "type": etype,
                "salience": float(round(e.salience, 3)),
                "relevance": int(round(e.salience * 100)),
                "wikipedia_url": str(e.metadata.get("wikipedia_url", "")),
                "mid": str(e.metadata.get("mid", "")),
            }
    entities = list(entity_map.values())
    if progress: progress.progress(0.75, "Google NLP: extracting topical category…")
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

def clean_entity_for_wiki(name):
    name = name.replace("’", "'")
    name = re.sub(r'[\u2013\u2014]', '-', name)
    name = re.sub(r'[^\w\s\-]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    name = name.title()
    return name.replace(" ", "_")

def make_progress_bar(percent, colour):
    light = adjust_colour(colour, light=True)
    dark = adjust_colour(colour, light=False)
    return f"""
    <div style="width:100%;max-width:120px;background:{light};height:22px;border-radius:14px;position:relative;overflow:hidden;">
      <div style="background:{dark};width:{percent}%;height:100%;border-radius:14px;transition:width 0.2s;"></div>
      <span style="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-weight:600;color:#fff;text-shadow:0 1px 4px #0003;font-size:0.98em;">{percent}%</span>
    </div>
    """

def highlight_entities_in_content(text, entities):
    if not text:
        return ""
    sorted_ents = sorted(entities, key=lambda e: -len(e["name"]))
    def highlight(match):
        word = match.group(0)
        ent = next((e for e in sorted_ents if e["name"].lower() == word.lower()), None)
        if not ent:
            return word
        colour = ENTITY_TYPE_COLOURS.get(ent["type"], "#adb5bd")
        dark = adjust_colour(colour, light=False)
        return (
            f'<span style="background:{colour};color:#222;padding:0px 4px 0px 4px;border-radius:4px;'
            f'display:inline-block;margin:0px 1.5px 0px 0;line-height:1.4;font-size:1em;vertical-align:middle;" '
            f'title="{ent["type"]} | Relevance: {ent["relevance"]}%">'
            f'{html.escape(word)}'
            f' <span style="background:{dark};color:#fff;border-radius:2px;font-size:0.67em;padding:0px 4px 0px 4px;margin-left:3px;">{ent["type"]}</span>'
            f'</span>'
        )
    entity_names = [re.escape(e["name"]) for e in sorted_ents]
    pattern = r'\b(' + "|".join(entity_names) + r')\b'
    return re.sub(pattern, highlight, text, flags=re.IGNORECASE)

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

# ---- MAIN ANALYSIS ----
if mode == "By URL":
    url = st.text_input("Enter URL to fetch (auto-adds https:// if missing):")
    if url and not url.startswith("http"):
        url = "https://" + url.lstrip("/")
    if st.button("Analyse"):
        progress = st.progress(0, "Starting…")
        try:
            progress.progress(0.10, "Fetching URL…")
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"}
            response = requests.get(url, headers=headers)
            progress.progress(0.20, "Fetched. Extracting visible text…")
            html_code = response.text
            content_text = extract_visible_text(html_code)
            progress.progress(0.40, "Text extracted. Analysing entities…")
            entities, (category_path, category_conf) = get_entities_and_category(content_text, progress=progress)
            progress.progress(0.85, "Processing table and highlights…")
            st.session_state["entities"] = entities
            st.session_state["content_text"] = content_text
            st.session_state["category_path"] = category_path
            st.session_state["category_conf"] = category_conf
            st.session_state["request_count"] += 1
            progress.progress(1.0, "Done!")
        except Exception as e:
            st.error(f"Error: {e}")
            progress.empty()

elif mode == "Paste HTML":
    html_input = st.text_area("Paste HTML here", height=150)
    if st.button("Analyse"):
        progress = st.progress(0, "Starting…")
        try:
            progress.progress(0.10, "Extracting visible text…")
            content_text = extract_visible_text(html_input)
            progress.progress(0.35, "Analysing entities…")
            entities, (category_path, category_conf) = get_entities_and_category(content_text, progress=progress)
            progress.progress(0.85, "Processing table and highlights…")
            st.session_state["entities"] = entities
            st.session_state["content_text"] = content_text
            st.session_state["category_path"] = category_path
            st.session_state["category_conf"] = category_conf
            st.session_state["request_count"] += 1
            progress.progress(1.0, "Done!")
        except Exception as e:
            st.error(f"Error: {e}")
            progress.empty()

else:
    text_input = st.text_area("Paste plain text here", height=150)
    if st.button("Analyse"):
        progress = st.progress(0, "Starting…")
        try:
            progress.progress(0.25, "Analysing entities…")
            content_text = text_input
            entities, (category_path, category_conf) = get_entities_and_category(content_text, progress=progress)
            progress.progress(0.85, "Processing table and highlights…")
            st.session_state["entities"] = entities
            st.session_state["content_text"] = content_text
            st.session_state["category_path"] = category_path
            st.session_state["category_conf"] = category_conf
            st.session_state["request_count"] += 1
            progress.progress(1.0, "Done!")
        except Exception as e:
            st.error(f"Error: {e}")
            progress.empty()

# ---- Always use session state to persist after analysis
entities = st.session_state.get("entities", [])
content_text = st.session_state.get("content_text", "")
category_path = st.session_state.get("category_path", [])
category_conf = st.session_state.get("category_conf", None)

# --- CATEGORY (with green progress bar, left aligned) ---
if category_path and category_conf is not None:
    st.markdown(
        f'''
        <div style="display:flex;align-items:center;margin-bottom:16px;margin-top:14px;">
            <span style="color:#567;font-size:1.08em;padding-right:24px;">{' › '.join(category_path)}</span>
            <div style="background:#e3fbe3; border-radius:6px; height:20px; width:150px; display:inline-block; overflow:hidden;">
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
        colour = ENTITY_TYPE_COLOURS.get(row["type"], "#adb5bd")
        bar = make_progress_bar(row["relevance"], colour)
        wiki = row["wikipedia_url"]
        entity_name = row["name"]
        schema_links = get_schema_links(row["type"], entity_name)
        times_on_page = count_occurrences(content_text, entity_name)
        clean_wiki = clean_entity_for_wiki(entity_name)
        display_title = clean_wiki.replace("_", " ")
        if wiki:
            wiki_html = f'Google Wiki: <a href="{wiki}" target="_blank" rel="noopener">{display_title}</a>'
        else:
            guessed_url = f"https://en.wikipedia.org/wiki/{clean_wiki}"
            wiki_html = f'No Google Wiki, guessed Wiki: <a href="{guessed_url}" target="_blank" rel="noopener">{display_title}</a>'
        rows.append({
            "Entity": html.escape(entity_name),
            "Times": times_on_page,
            "Type": row["type"],
            "Relevance": bar,
            "Wikipedia": wiki_html,
            "Potential Schema Markup": schema_links
        })

    TOP_N = 20
    shown = rows[:TOP_N]
    extra = rows[TOP_N:]

    def table_html(rows):
        return (
            '<table style="width:100%; font-size:1em; border-collapse:collapse;">'
            '<tr>'
            '<th align="left" style="width:180px;">Entity</th>'
            '<th align="left" style="width:40px;">Times</th>'
            '<th align="left" style="width:60px;">Type</th>'
            '<th align="left" style="width:150px;">Relevance</th>'
            '<th align="left" style="width:320px;">Wikipedia</th>'
            '<th align="left" style="width:210px;">Potential Schema Markup</th>'
            '</tr>' +
            "".join(
                f'<tr>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Entity"]}</td>'
                f'<td style="padding:3px 6px;vertical-align:middle;">{r["Times"]}</td>'
                f'<td style="padding:3px 6px;vertical-align:middle;">{r["Type"]}</td>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Relevance"]}</td>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Wikipedia"]}</td>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Potential Schema Markup"]}</td>'
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

    csv_buffer = StringIO()
    pd.DataFrame([
        {
            "Entity": r["Entity"],
            "Times on Page": r["Times"],
            "Type": r["Type"],
            "Wikipedia": re.sub("<.*?>", "", r["Wikipedia"]),
            "Potential Schema Markup": re.sub("<.*?>", "", r["Potential Schema Markup"])
        }
        for r in rows
    ]).to_csv(csv_buffer, index=False)
    st.download_button("Download Entities as CSV", csv_buffer.getvalue(), file_name="entities.csv", mime="text/csv")

    st.markdown("### Content with Entities Highlighted")
    styled_content = highlight_entities_in_content(content_text, entities)
    if styled_content.strip():
        st.markdown(
            f'<div style="background: #fafbff; padding:1em 1.2em; border-radius:8px; line-height:1.45;">{styled_content}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No content to highlight or no entities found.")

st.markdown("---")
st.caption("© Simon 2025")
