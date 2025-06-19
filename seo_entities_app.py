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

# ---- Login FIRST ----
col1, col2, col3 = st.columns([2, 1, 2])
if "authenticated" not in st.session_state or not st.session_state["authenticated"]:
    with col2:
        st.markdown("### Login")
        pw_col1, pw_col2, pw_col3 = st.columns([3, 4, 2])
        with pw_col2:
            pw = st.text_input("Password", type="password", key="pw_input", max_chars=32)
        login = st.button("Login")
        if login or (pw and st.session_state.get("last_pw") != pw):
            st.session_state["last_pw"] = pw
            if pw == st.secrets["app_password"]:
                st.session_state["authenticated"] = True
                rerun()
            elif pw:
                st.error("Incorrect password.")
        st.stop()

LIMIT = 15
if "request_count" not in st.session_state:
    st.session_state["request_count"] = 0
if st.session_state["request_count"] >= LIMIT:
    st.error("Rate limit exceeded. Please wait or reload the app later.")
    st.stop()

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

def clean_entity_name(name):
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r"[‘’´`]", "'", name)
    name = re.sub(r'[“”]', '"', name)
    name = re.sub(r"[\u2013\u2014]", "-", name)
    name = re.sub(r"[^\w\s\-]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name.encode("ascii", "ignore").decode("ascii")
    return name.title()

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

def make_progress_bar(percent, colour):
    light = adjust_colour(colour, light=True)
    dark = adjust_colour(colour, light=False)
    return f"""
    <div style="width:100%;max-width:110px;background:{light};height:20px;border-radius:11px;position:relative;overflow:hidden;">
      <div style="background:{dark};width:{percent}%;height:100%;border-radius:11px;transition:width 0.2s;"></div>
      <span style="position:absolute;top:0;left:0;width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-weight:500;color:#222;text-shadow:0 1px 4px #fff7;">{percent}%</span>
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
            f'<span style="background:{colour};color:#222;padding:0px 4px;border-radius:3px;'
            f'display:inline-block;margin:0px 1px 0px 0;line-height:1.3;font-size:1em;vertical-align:middle;" '
            f'title="{ent["type"]} | Relevance: {ent["relevance"]}%">'
            f'{html.escape(word)}'
            f' <span style="background:{dark};color:#fff;border-radius:2px;font-size:0.68em;padding:0px 4px 0px 4px;margin-left:3px;">{ent["type"]}</span>'
            f'</span>'
        )
    entity_names = [re.escape(e["name"]) for e in sorted_ents]
    pattern = r'\b(' + "|".join(entity_names) + r')\b'
    return re.sub(pattern, highlight, text, flags=re.IGNORECASE)

def page_topic_salience(keyword, category_path, entities, content_text):
    keyword = keyword.strip().lower()
    for ent in entities:
        if ent["name"].lower() == keyword:
            return f"Direct entity match ({ent['relevance']}%)"
    for ent in entities:
        if keyword in ent["name"].lower() or ent["name"].lower() in keyword:
            return f"Related entity: '{ent['name']}' ({ent['relevance']}%)"
    cat_str = " ".join(category_path).lower() if category_path else ""
    if keyword in cat_str:
        return f"Matches Google category: {' › '.join(category_path)}"
    if keyword in content_text.lower():
        return f"Found in visible page text"
    return "No strong entity/category match"

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

url_autorun = False
if mode == "By URL":
    url = st.text_input("Enter URL to fetch:")
    if url and not url.startswith("http"):
        url = "https://" + url.lstrip("/")
        url_autorun = True
    if st.button("Analyse") or url_autorun:
        progress = st.progress(0, "Starting…")
        try:
            progress.progress(0.10, "Fetching URL…")
            headers = {"User-Agent": "Mozilla/5.0"}
            response = requests.get(url, headers=headers)
            progress.progress(0.20, "Fetched. Extracting visible text…")
            html_code = response.text
            content_text = extract_visible_text(html_code)
            progress.progress(0.40, "Text extracted. Analysing entities…")
            entities, (category_path, category_conf) = get_entities_and_category(content_text, progress=progress)
            progress.progress(0.85, "Processing table and highlights…")
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
            st.session_state["request_count"] += 1
            progress.progress(1.0, "Done!")
        except Exception as e:
            st.error(f"Error: {e}")
            progress.empty()

# --- Topic Salience Field in 3-Column Row ---
if entities and (category_path or content_text):
    st.markdown("### Check salience to topic/keyword")
    tc1, tc2, tc3 = st.columns([2, 3, 1])
    with tc2:
        topic_word = st.text_input(
            "Keyword/topic",
            key="topic_word",
            max_chars=40,
            placeholder="e.g. cash for cars",
            label_visibility="collapsed",
            help="Check if your main target phrase is a direct or related entity or matches the Google category."
        )
    submit = tc2.button("Check", key="check_topic")
    salience_result = ""
    if (submit or st.session_state.get("auto_check")) and topic_word:
        salience_result = page_topic_salience(topic_word, category_path, entities, content_text)
        st.session_state["auto_check"] = False
    if topic_word and not submit:
        st.session_state["auto_check"] = True
    if salience_result:
        tc2.info(salience_result)

# --- CATEGORY (with green progress bar) ---
if category_path and category_conf is not None:
    st.markdown(f"#### From your description, Google attributes this category to this entity")
    st.markdown(
        f'''
        <div style="display:flex;align-items:center;">
            <span style="color:#567;font-size:1.08em;">{' › '.join(category_path)}</span>
            <div style="background:#e3fbe3; border-radius:6px; margin-left:20px; height:18px; width:130px; display:inline-block; overflow:hidden;">
                <div style="background:#38b000; width:{category_conf}%; height:100%;"></div>
            </div>
            <span style="color:#38b000; margin-left:10px;">{category_conf}%</span>
        </div>
        ''',
        unsafe_allow_html=True
    )

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
        clean_wiki = entity_name.replace(" ", "_")
        display_title = clean_wiki.replace("_", " ")
        if wiki:
            wiki_html = f'Google Wiki: <a href="{wiki}" target="_blank" rel="noopener">{display_title}</a>'
        else:
            guessed_url = f"https://en.wikipedia.org/wiki/{clean_wiki}"
            wiki_html = f'No Google Wiki, guessed Wiki: <a href="{guessed_url}" target="_blank" rel="noopener">{display_title}</a>'
        rows.append({
            "Entity": html.escape(entity_name),
            "Type": row["type"],
            "Relevance": bar,
            "Wikipedia": wiki_html
        })

    TOP_N = 20
    shown = rows[:TOP_N]
    extra = rows[TOP_N:]

    def table_html(rows):
        return (
            '<table style="width:100%; font-size:1em; border-collapse:collapse;">'
            '<tr>'
            '<th align="left" style="width:180px;">Entity</th>'
            '<th align="left" style="width:60px;">Type</th>'
            '<th align="left" style="width:130px;">Relevance</th>'
            '<th align="left" style="width:320px;">Wikipedia</th>'
            '</tr>' +
            "".join(
                f'<tr>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Entity"]}</td>'
                f'<td style="padding:3px 6px;vertical-align:middle;">{r["Type"]}</td>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Relevance"]}</td>'
                f'<td style="padding:3px 8px;vertical-align:middle;">{r["Wikipedia"]}</td>'
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
            "Type": r["Type"],
            "Wikipedia": re.sub("<.*?>", "", r["Wikipedia"])
        }
        for r in rows
    ]).to_csv(csv_buffer, index=False)
    st.download_button("Download Entities as CSV", csv_buffer.getvalue(), file_name="entities.csv", mime="text/csv")

    st.markdown("### Content with Entities Highlighted")
    styled_content = highlight_entities_in_content(content_text, entities)
    if styled_content.strip():
        st.markdown(
            f'<div style="background: #fafbff; padding:0.6em 1.1em; border-radius:8px; line-height:1.35;">{styled_content}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.info("No content to highlight or no entities found.")

st.markdown("---")
st.caption("© Simon 2025")
