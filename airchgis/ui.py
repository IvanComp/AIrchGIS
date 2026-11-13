

from pathlib import Path

import streamlit as st

from .paths import LOGO_PATH


PALETTE = {
    "brown_950": "#0f0c08",
    "brown_900": "#15100b",
    "brown_850": "#1b130d",
    "brown_800": "#21170f",
    "brown_700": "#302014",
    "brown_600": "#4a2c16",
    "gold_600": "#c99a26",
    "gold_500": "#d4af37",
    "gold_400": "#f1c75b",
    "gold_300": "#ffe9a8",
    "text": "#f7ecd7",
    "muted": "#c7b899",
}

def logo_svg():

    try:
        markup = " ".join(Path(LOGO_PATH).read_text(encoding="utf-8").splitlines())
    except OSError:
        return ""
    return markup.replace("<svg ", '<svg class="as-logo-svg" ', 1)


def brand_markup(subtitle="AI-assisted archaeological GIS"):
    return f"""
    <div class="as-brandbar">
        <div class="as-logo">{logo_svg()}</div>
        <div class="as-brandtext">
            <div class="as-brand"><span>AI</span>rchGIS</div>
            <div class="as-brand-sub">{subtitle}</div>
        </div>
    </div>
    """


def source_code_markup():
    return (
        '<a class="as-source-link" href="https://github.com/IvanComp/AIrchGIS" '
        'target="_blank" rel="noopener noreferrer">'
        '<svg viewBox="0 0 24 24" aria-hidden="true" fill="currentColor">'
        '<path d="M12 .297C5.37.297 0 5.67 0 12.297c0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577v-2.234c-3.338.726-4.043-1.416-4.043-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.09-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.835 2.807 1.305 3.492.998.108-.776.418-1.305.762-1.605-2.665-.305-5.467-1.334-5.467-5.931 0-1.31.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23a11.52 11.52 0 016.006 0c2.291-1.552 3.297-1.23 3.297-1.23.654 1.652.243 2.873.119 3.176.769.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .322.216.694.825.576C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>'
        '</svg><span>Source Code v1.0.0</span></a>'
    )


def section_title(title, eyebrow="", hint=""):

    eyebrow_html = f'<div class="as-eyebrow">{eyebrow}</div>' if eyebrow else ""
    hint_html = f'<p class="as-section-hint">{hint}</p>' if hint else ""
    st.markdown(
        f"""
        <div class="as-section">
            {eyebrow_html}
            <h2 class="as-section-title">{title}</h2>
            {hint_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def inject_styles():

    st.markdown(f"<style>{STYLESHEET}</style>", unsafe_allow_html=True)


STYLESHEET = """
@import url("https://fonts.googleapis.com/css2?family=Cinzel:wght@500;600;700&family=Inter:wght@400;500;600&display=swap");

[data-baseweb="select"], [data-baseweb="select"] *, [data-baseweb="popover"] li, [role="option"],
[data-testid="stSelectbox"] div, [data-testid="stMultiSelect"] div, [data-testid="stExpander"] summary {
    cursor: pointer !important;
}
:root {
    --as-brown-950: #0f0c08;
    --as-brown-900: #15100b;
    --as-brown-850: #1b130d;
    --as-brown-800: #21170f;
    --as-brown-700: #302014;
    --as-brown-600: #4a2c16;
    --as-gold-600: #c99a26;
    --as-gold-500: #d4af37;
    --as-gold-400: #f1c75b;
    --as-gold-300: #ffe9a8;
    --as-text: #f7ecd7;
    --as-muted: #c7b899;
    --as-line: rgba(212, 175, 55, 0.24);
    --as-line-strong: rgba(241, 199, 91, 0.5);
    --as-ease: cubic-bezier(0.22, 0.61, 0.36, 1);
}


header[data-testid="stHeader"],
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"],
div[data-testid="stDeployButton"],
button[data-testid="stDeployButton"],
.stDeployButton,
#MainMenu,
footer {
    display: none;
    visibility: hidden;
}


.stApp {
    background: var(--as-brown-950);
    color: var(--as-text);
}
.stApp::before {
    content: "";
    position: fixed;
    inset: -20vmax;
    z-index: 0;
    pointer-events: none;
    background:
        radial-gradient(38vmax 30vmax at 18% 8%, rgba(241, 199, 91, 0.13), transparent 62%),
        radial-gradient(34vmax 28vmax at 84% 22%, rgba(184, 115, 51, 0.14), transparent 66%),
        radial-gradient(44vmax 34vmax at 62% 96%, rgba(212, 175, 55, 0.09), transparent 68%);
    animation: as-drift 34s ease-in-out infinite alternate;
}
.stApp::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
    opacity: 0.5;
    background-image: url("data:image/svg+xml;utf8,\
<svg xmlns='http://www.w3.org/2000/svg' width='420' height='420' viewBox='0 0 420 420'>\
<g fill='none' stroke='%23d4af37' stroke-opacity='0.075' stroke-width='1.1'>\
<path d='M-20 92c70-46 140-52 210-18s140 28 230-22'/>\
<path d='M-20 146c74-42 146-46 214-12s138 24 226-26'/>\
<path d='M-20 206c78-36 150-38 216-6s136 20 224-30'/>\
<path d='M-20 268c80-30 152-30 216 0s134 16 224-34'/>\
<path d='M-20 332c82-24 154-22 216 6s132 12 224-38'/>\
</g></svg>");
    animation: as-contours 60s linear infinite;
}
.block-container {
    position: relative;
    z-index: 1;
    padding-top: 0.9rem;
    padding-bottom: 3rem;
}

@keyframes as-drift {
    0%   { transform: translate3d(0, 0, 0) scale(1); }
    50%  { transform: translate3d(2.5%, -2%, 0) scale(1.06); }
    100% { transform: translate3d(-2%, 2.5%, 0) scale(1.02); }
}
@keyframes as-contours {
    from { background-position: 0 0; }
    to   { background-position: 420px 210px; }
}


.as-brandbar {
    align-items: center;
    display: flex;
    gap: 0.7rem;
    min-width: 0;
}
.as-logo {
    filter: drop-shadow(0 6px 16px rgba(212, 175, 55, 0.22));
    flex: 0 0 auto;
    height: 46px;
    transition: transform 0.5s var(--as-ease), filter 0.4s var(--as-ease);
    width: 46px;
}
.as-logo:hover {
    filter: drop-shadow(0 8px 22px rgba(241, 199, 91, 0.45));
    transform: rotate(-6deg) scale(1.06);
}
.as-logo-svg { display: block; height: 100%; width: 100%; }
.as-brandtext { min-width: 0; overflow: hidden; }
.as-brand {
    background: linear-gradient(96deg, var(--as-gold-300) 0%, var(--as-gold-400) 34%, #fff6df 50%, var(--as-gold-400) 66%, var(--as-gold-600) 100%);
    background-size: 260% 100%;
    -webkit-background-clip: text;
    background-clip: text;
    color: transparent;
    font-size: 1.34rem;
    font-weight: 800;
    letter-spacing: 0.01em;
    line-height: 1.05;
    margin: 0;
    white-space: nowrap;
    animation: as-sheen 9s ease-in-out infinite;
}
.as-brand span { font-weight: 400; }
.as-brand-sub {
    color: var(--as-muted);
    font-size: 0.62rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    margin-top: 0.16rem;
    overflow: hidden;
    text-overflow: ellipsis;
    text-transform: uppercase;
    white-space: nowrap;
}
@keyframes as-sheen {
    0%, 100% { background-position: 100% 50%; }
    50%      { background-position: 0% 50%; }
}


.as-nav-rule {
    background: linear-gradient(90deg, transparent, var(--as-line-strong) 18%, var(--as-line-strong) 82%, transparent);
    height: 1px;
    margin: 0.75rem 0 1.05rem;
    position: relative;
    overflow: hidden;
}
.as-nav-rule::after {
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 22%;
    background: linear-gradient(90deg, transparent, var(--as-gold-300), transparent);
    animation: as-scan 6.5s var(--as-ease) infinite;
}
@keyframes as-scan {
    0%   { transform: translateX(-120%); opacity: 0; }
    12%  { opacity: 1; }
    88%  { opacity: 1; }
    100% { transform: translateX(560%); opacity: 0; }
}

div[data-testid="stButton"] > button {
    background: linear-gradient(180deg, rgba(48, 32, 20, 0.9), rgba(27, 19, 13, 0.9));
    border: 1px solid rgba(212, 175, 55, 0.34);
    border-radius: 10px;
    color: var(--as-text);
    font-weight: 700;
    min-height: 2.6rem;
    overflow: hidden;
    position: relative;
    transition: transform 0.22s var(--as-ease), border-color 0.22s var(--as-ease),
                box-shadow 0.28s var(--as-ease), color 0.22s var(--as-ease);
}
div[data-testid="stButton"] > button::after {
    content: "";
    position: absolute;
    inset: 0 auto 0 -60%;
    width: 45%;
    background: linear-gradient(100deg, transparent, rgba(255, 246, 223, 0.22), transparent);
    transform: skewX(-18deg);
    transition: left 0.55s var(--as-ease);
}
div[data-testid="stButton"] > button:hover {
    border-color: var(--as-gold-400);
    box-shadow: 0 10px 24px -12px rgba(241, 199, 91, 0.65);
    color: var(--as-gold-300);
    transform: translateY(-2px);
}
div[data-testid="stButton"] > button:hover::after { left: 115%; }
div[data-testid="stButton"] > button:active { transform: translateY(0); }
div[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(180deg, var(--as-gold-300), var(--as-gold-500) 62%, var(--as-gold-600));
    border-color: var(--as-gold-300);
    color: #16100a;
    box-shadow: 0 8px 22px -10px rgba(241, 199, 91, 0.8);
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
    color: #16100a;
    box-shadow: 0 14px 30px -10px rgba(241, 199, 91, 0.95);
}


div[data-testid="stButton"] > button p { white-space: nowrap; }
@media (max-width: 1560px) {
    .as-utility-label { display: none; }
    div[data-testid="stButton"] > button { font-size: 0.86rem; }
}
@media (max-width: 1280px) {
    .as-brand-sub { display: none; }
    .as-utility-link { font-size: 0.72rem; padding: 0.3rem 0.55rem; }
}


.as-utility {
    align-items: center;
    display: flex;
    gap: 0.45rem;
    justify-content: flex-end;
}
.as-utility-label {
    color: var(--as-muted);
    font-size: 0.68rem;
    font-weight: 800;
    letter-spacing: 0.12em;
    margin-right: 0.2rem;
    text-transform: uppercase;
}
.as-utility-link {
    align-items: center;
    background: rgba(33, 23, 15, 0.6);
    border: 1px solid rgba(212, 175, 55, 0.24);
    border-radius: 999px;
    color: #eadcc5 !important;
    display: inline-flex;
    font-size: 0.76rem;
    font-weight: 700;
    gap: 0.34rem;
    padding: 0.34rem 0.66rem;
    text-decoration: none !important;
    transition: transform 0.22s var(--as-ease), border-color 0.22s var(--as-ease),
                background 0.22s var(--as-ease), color 0.22s var(--as-ease);
    white-space: nowrap;
}
.as-utility-icon { font-size: 0.9rem; line-height: 1; }
.as-utility-link:hover {
    background: rgba(212, 175, 55, 0.16);
    border-color: var(--as-gold-400);
    color: var(--as-gold-300) !important;
    transform: translateY(-2px);
}


.as-section { margin: 0.2rem 0 0.9rem; }
.as-eyebrow {
    color: var(--as-gold-400);
    font-size: 0.7rem;
    font-weight: 800;
    letter-spacing: 0.16em;
    text-transform: uppercase;
}
.as-section-title {
    color: #fff6df;
    font-size: 1.62rem;
    line-height: 1.1;
    margin: 0.18rem 0 0.3rem;
    position: relative;
}
.as-section-title::after {
    content: "";
    display: block;
    height: 2px;
    margin-top: 0.42rem;
    width: 72px;
    background: linear-gradient(90deg, var(--as-gold-300), rgba(212, 175, 55, 0));
    animation: as-grow 1.1s var(--as-ease) both;
}
.as-section-hint {
    color: var(--as-muted);
    font-size: 0.86rem;
    margin: 0.35rem 0 0;
    max-width: 78ch;
}
@keyframes as-grow { from { width: 0; opacity: 0; } to { width: 72px; opacity: 1; } }


section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, rgba(33, 23, 15, 0.96), rgba(21, 16, 11, 0.96));
    border-right: 1px solid var(--as-line);
}
section[data-testid="stSidebar"] * { position: relative; }

div[data-testid="stMetric"] {
    background: linear-gradient(160deg, rgba(255, 246, 223, 0.06), rgba(255, 246, 223, 0.015));
    border: 1px solid rgba(212, 175, 55, 0.2);
    border-radius: 12px;
    overflow: hidden;
    padding: 0.6rem 0.75rem;
    position: relative;
    transition: transform 0.26s var(--as-ease), border-color 0.26s var(--as-ease), box-shadow 0.3s var(--as-ease);
    animation: as-rise 0.55s var(--as-ease) both;
}
div[data-testid="stMetric"]::before {
    content: "";
    position: absolute;
    inset: 0 0 auto 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--as-gold-400), transparent);
    opacity: 0.55;
    transform: translateX(-100%);
    animation: as-sweepline 5.5s var(--as-ease) infinite;
}
div[data-testid="stMetric"]:hover {
    border-color: var(--as-line-strong);
    box-shadow: 0 16px 34px -22px rgba(241, 199, 91, 0.9);
    transform: translateY(-3px);
}
div[data-testid="stMetricValue"] { color: var(--as-gold-300); }
@keyframes as-sweepline {
    0%, 55% { transform: translateX(-100%); }
    100%    { transform: translateX(100%); }
}
@keyframes as-rise {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
}

div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] { animation: as-rise 0.5s var(--as-ease) both; }
div[data-testid="stExpander"] {
    border: 1px solid var(--as-line);
    border-radius: 12px;
    overflow: hidden;
    transition: border-color 0.26s var(--as-ease), box-shadow 0.3s var(--as-ease);
}
div[data-testid="stExpander"]:hover {
    border-color: var(--as-line-strong);
    box-shadow: 0 14px 30px -24px rgba(241, 199, 91, 0.8);
}
div[data-testid="stExpander"] summary:hover { color: var(--as-gold-300); }

div[data-testid="stDataFrame"], div[data-testid="stTable"] {
    border-radius: 10px;
    overflow: hidden;
}
iframe { border-radius: 12px; }


div[data-testid="stRadio"] [role="radiogroup"] label,
div[data-testid="stCheckbox"] label,
div[data-testid="stSlider"] label,
div[data-testid="stSelectbox"] label,
div[data-testid="stMultiSelect"] label,
div[data-testid="stNumberInput"] label,
div[data-testid="stTextInput"] label,
div[data-testid="stDateInput"] label { color: var(--as-text); }

div[data-baseweb="select"] > div,
div[data-testid="stTextInput"] input,
div[data-testid="stNumberInput"] input,
div[data-testid="stDateInput"] input,
textarea {
    background-color: rgba(48, 32, 20, 0.72) !important;
    border-color: rgba(212, 175, 55, 0.26) !important;
    color: var(--as-text) !important;
    transition: border-color 0.22s var(--as-ease), box-shadow 0.22s var(--as-ease);
}
div[data-baseweb="select"] > div:hover,
div[data-testid="stTextInput"] input:focus,
div[data-testid="stNumberInput"] input:focus,
textarea:focus {
    border-color: var(--as-gold-400) !important;
    box-shadow: 0 0 0 3px rgba(241, 199, 91, 0.14) !important;
}


div[data-testid="stSpinner"] > div { border-top-color: var(--as-gold-400) !important; }
div[data-testid="stSpinner"] { color: var(--as-gold-300); }
div[data-testid="stAlert"] {
    border-left: 3px solid var(--as-gold-500);
    border-radius: 10px;
    animation: as-rise 0.45s var(--as-ease) both;
}


.as-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.15rem 0 0.75rem; }
.as-chip {
    align-items: center;
    background: rgba(212, 175, 55, 0.1);
    border: 1px solid rgba(212, 175, 55, 0.26);
    border-radius: 999px;
    color: var(--as-text);
    display: inline-flex;
    font-size: 0.74rem;
    font-weight: 600;
    gap: 0.34rem;
    padding: 0.24rem 0.6rem;
    transition: transform 0.2s var(--as-ease), background 0.2s var(--as-ease);
    animation: as-rise 0.5s var(--as-ease) both;
}
.as-chip:hover { background: rgba(212, 175, 55, 0.2); transform: translateY(-2px); }
.as-chip b { color: var(--as-gold-300); font-weight: 800; }
.as-chip--hot { border-color: rgba(239, 71, 111, 0.55); background: rgba(239, 71, 111, 0.14); }
.as-chip--cool { border-color: rgba(76, 201, 240, 0.45); background: rgba(76, 201, 240, 0.12); }

.as-legend {
    border: 1px solid var(--as-line);
    border-radius: 12px;
    color: var(--as-muted);
    font-size: 0.8rem;
    line-height: 1.5;
    padding: 0.75rem 0.9rem;
}
.as-legend b { color: var(--as-gold-300); }


::-webkit-scrollbar { height: 10px; width: 10px; }
::-webkit-scrollbar-track { background: rgba(15, 12, 8, 0.6); }
::-webkit-scrollbar-thumb {
    background: linear-gradient(180deg, var(--as-gold-600), var(--as-brown-600));
    border-radius: 999px;
}
::-webkit-scrollbar-thumb:hover { background: var(--as-gold-500); }


.as-db-heading {
    align-items: end;
    display: flex;
    gap: 1rem;
    justify-content: space-between;
    margin: 0.2rem 0 1rem;
}
.as-db-eyebrow {
    color: #d8c08a;
    font-size: 0.74rem;
    font-weight: 800;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}
.as-db-heading h1 {
    color: #fff6df;
    font-size: 2rem;
    line-height: 1.05;
    margin: 0.1rem 0 0;
}
.as-db-source {
    border: 1px solid rgba(212, 175, 55, 0.35);
    border-radius: 10px;
    color: var(--as-gold-400);
    font-weight: 900;
    padding: 0.55rem 0.75rem;
    animation: as-breathe 5s ease-in-out infinite;
}
@keyframes as-breathe {
    0%, 100% { box-shadow: 0 0 0 0 rgba(241, 199, 91, 0); }
    50%      { box-shadow: 0 0 0 6px rgba(241, 199, 91, 0.07); }
}
.as-db-filter-band {
    border-bottom: 1px solid var(--as-line);
    border-top: 1px solid var(--as-line);
    margin-bottom: 0.9rem;
    padding: 0.75rem 0 0.35rem;
}
.as-db-vitrine {
    background: linear-gradient(120deg, rgba(255, 255, 255, 0.07), rgba(255, 255, 255, 0.01)), #1f160f;
    border: 1px solid rgba(212, 175, 55, 0.36);
    border-radius: 14px;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.12);
    margin-bottom: 0.7rem;
    overflow: hidden;
    position: relative;
    animation: as-rise 0.6s var(--as-ease) both;
}
.as-db-glass {
    background: linear-gradient(100deg, rgba(255,255,255,0.2), rgba(255,255,255,0.02) 42%, rgba(255,255,255,0.12));
    background-size: 220% 100%;
    height: 58px;
    animation: as-sheen 11s ease-in-out infinite;
}
.as-db-object {
    align-items: center;
    background: radial-gradient(circle at 35% 28%, #ffe5a1, #b4862b 45%, #5b3a17 76%);
    border: 1px solid rgba(255, 235, 175, 0.55);
    border-radius: 999px;
    box-shadow: 0 18px 40px rgba(0,0,0,0.4), inset 0 6px 16px rgba(255,255,255,0.2);
    color: #21170f;
    display: flex;
    font-weight: 900;
    height: 116px;
    justify-content: center;
    margin: -22px auto 0;
    transition: transform 0.5s var(--as-ease);
    width: 116px;
}
.as-db-vitrine:hover .as-db-object { transform: translateY(-3px) scale(1.03); }
.as-db-object span { font-size: 0.9rem; }
.as-db-plaque { padding: 1rem 1.05rem 1.1rem; }
.as-db-plaque-top {
    color: #d8c08a;
    font-size: 0.78rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.as-db-plaque h2 {
    color: #fff6df;
    font-size: 1.25rem;
    line-height: 1.16;
    margin: 0.25rem 0 0.6rem;
}
.as-db-tags { display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.75rem; }
.as-db-tags span {
    background: rgba(212, 175, 55, 0.12);
    border: 1px solid rgba(212, 175, 55, 0.24);
    border-radius: 999px;
    color: var(--as-text);
    font-size: 0.75rem;
    padding: 0.22rem 0.5rem;
    transition: background 0.2s var(--as-ease), transform 0.2s var(--as-ease);
}
.as-db-tags span:hover { background: rgba(212, 175, 55, 0.24); transform: translateY(-1px); }
.as-db-plaque p {
    color: #eadcc5;
    font-size: 0.9rem;
    line-height: 1.45;
    margin: 0 0 0.85rem;
    max-height: 260px;
    overflow: auto;
}
.as-db-coords {
    border-left: 3px solid var(--as-gold-500);
    color: var(--as-gold-400);
    font-size: 0.82rem;
    font-weight: 800;
    margin-bottom: 0.85rem;
    padding-left: 0.55rem;
}
.as-db-source-line {
    border-top: 1px solid rgba(212, 175, 55, 0.18);
    color: #cdbf9f;
    font-size: 0.78rem;
    line-height: 1.35;
    margin-top: 0.55rem;
    padding-top: 0.55rem;
}
.as-db-table-title {
    color: #fff6df;
    font-size: 1rem;
    font-weight: 900;
    margin: 1rem 0 0.35rem;
}

@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
    }
}


.st-key-terrain_upload { max-width: 960px; margin: .3rem auto 0; }
.st-key-terrain_upload [data-testid="stFileUploader"] { width: 64%; margin-inline: auto; }
.st-key-terrain_upload [data-testid="stFileUploader"] > label { justify-content: center; padding: .55rem 0 .65rem; margin-bottom: .4rem; }
.st-key-terrain_upload [data-testid="stFileUploader"] > label p { color: var(--as-gold-400); font-weight: 700; font-size: 1.05rem; line-height: 1.5; text-align: center; }
.st-key-terrain_upload [data-testid="stFileUploaderDropzone"] {
    display: flex; flex-direction: column; justify-content: center; gap: .85rem;
    box-sizing: border-box; min-height: 180px; padding: 1.4rem 1.5rem; text-align: center; align-items: center;
    border: 1.5px dashed rgba(212,175,55,.48); border-radius: 18px;
    background: rgba(33,23,15,.68);
    transition: border-color .25s, background .25s, box-shadow .25s;
}
.st-key-terrain_upload [data-testid="stFileUploaderDropzone"]:hover,
.st-key-terrain_upload [data-testid="stFileUploaderDropzone"]:focus-within {
    border-color: var(--as-gold-400); background: rgba(48,32,20,.85);
    box-shadow: 0 16px 40px -24px rgba(241,199,91,.35);
}
.st-key-terrain_upload [data-testid="stFileUploaderDropzoneInstructions"] { display: flex; flex-direction: column; gap: .6rem; margin: 0; }
.st-key-terrain_upload [data-testid="stFileUploaderDropzoneInstructions"] svg { width: 44px; height: 44px; color: var(--as-gold-400); }
.st-key-terrain_upload [data-testid="stFileUploaderDropzone"]::before { content: "Drop your files here"; color: var(--as-text); font-size: 1.15rem; font-weight: 600; }
.st-key-terrain_upload [data-testid="stFileUploaderDropzone"] > span { align-self: center; width: auto; }
.st-key-terrain_upload [data-testid="stFileUploaderDropzone"] button { border-color: var(--as-gold-500); border-radius: 10px; padding: .55rem 1.4rem; }
.st-key-terrain_upload ol.as-upload-steps { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); position: relative; list-style: none; padding: 0; margin: 1.8rem 0 0; gap: 0; }
.as-upload-steps::before { content: ""; position: absolute; top: 37px; left: 16.666%; right: 16.666%; height: 1px; background: linear-gradient(90deg, transparent, var(--as-line-strong) 8%, var(--as-line-strong) 92%, transparent); }
.as-upload-steps::after { content: ""; position: absolute; top: 37px; left: 16.666%; right: 16.666%; height: 1px; z-index: 0; background: linear-gradient(90deg, transparent, var(--as-gold-300), transparent) no-repeat; background-size: 22% 100%; animation: as-step-scan 6.5s var(--as-ease) infinite; }
@keyframes as-step-scan { 0% { background-position: -30% 0; opacity: 0; } 12%,88% { opacity: 1; } 100% { background-position: 130% 0; opacity: 0; } }
.as-upload-steps li { margin: 0; z-index: 1; position: relative; min-width: 0; padding: 0 clamp(10px, 1.8vw, 28px); text-align: center; }
.as-step-number { box-sizing: border-box; width: 76px; height: 76px; margin: 0 auto 18px; border: 1px solid #9d7038; background: #24170f; border-radius: 50%; display: grid; place-items: center; color: #e4bf6b; font: 600 24px Cinzel, serif; position: relative; }
.st-key-terrain_upload .as-upload-steps h3 { color: var(--as-text); font: 600 16px/1.5 Cinzel, serif; padding: 0; margin: 0 0 12px; min-height: 50px; }
.st-key-terrain_upload .as-upload-steps p { color: var(--as-muted); font: 400 13px/1.7 Inter, sans-serif; margin: 0; }
.as-upload-steps [data-testid="stHeaderActionElements"] { display: none; }
div[data-testid="stButton"] > button:disabled { opacity: .45; cursor: not-allowed; transform: none; box-shadow: none; }
div[data-testid="stButton"] > button:disabled::after { display: none; }
@media (max-width: 760px) {
    .st-key-terrain_upload { margin-top: 1rem; }
    .st-key-terrain_upload ol.as-upload-steps { grid-template-columns: 1fr; gap: 2rem; margin-top: 2rem; }
    .as-upload-steps::before,.as-upload-steps::after { display: none; }
    .as-step-number { margin-bottom: 1rem; }
    .st-key-terrain_upload .as-upload-steps h3 { min-height: 0; }
    div[data-testid="stButton"] > button p { white-space: normal; }
}


.st-key-nav_guide button[kind] { min-height: 46px; background: rgba(212,175,55,.04); border: 0; border-bottom: 2px solid #a77935; border-radius: 7px 7px 0 0; color: var(--as-gold-300); font-weight: 500; box-shadow: none; }
.st-key-nav_guide button[kind]:hover { background: rgba(212,175,55,.1); border-color: var(--as-gold-300); box-shadow: 0 8px 18px -16px #ffe9a8; transform: none; }
.st-key-nav_guide button[kind]::after { display: none; }
.st-key-nav_guide button[kind="primary"] { background: rgba(212,175,55,.13); border-color: var(--as-gold-300); }
.st-key-nav_cases { padding: .65rem .85rem .75rem 1.25rem; border-left: 1px solid var(--as-line); background: rgba(33,23,15,.38); border-radius: 0 12px 12px 0; }
.st-key-nav_cases > div { gap: .5rem; }
.as-cases-heading { display: flex; align-items: center; gap: .65rem; line-height: 1; margin-bottom: .1rem; }
.as-cases-heading > span { color: var(--as-muted); font-size: .7rem; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; }
.st-key-nav_cases button[kind]:disabled { opacity: .65; background: transparent; border-color: rgba(199,184,153,.18); color: var(--as-muted); min-height: 3.4rem; font-weight: 500; }
@media (max-width: 760px) { .st-key-nav_cases { border-left: 0; border-top: 1px solid var(--as-line); border-radius: 0 0 12px 12px; padding: 1rem .6rem .75rem; } }

.as-logo { height: 58px; width: 58px; }
.as-brand { font-size: 1.75rem; }
.as-brand-sub { display: block; font-size: .76rem; letter-spacing: .055em; margin-top: .3rem; }
.as-brandbar { gap: .8rem; }
.as-nav-rule { margin: .5rem 0 .35rem; }
@media (max-width: 1280px) { .as-brand-sub { font-size: .68rem; } }
@media (max-width: 760px) {
    .as-brand-sub { font-size: .65rem; }
    .st-key-terrain_upload [data-testid="stFileUploader"] { width: 100%; }
}
@media (min-width: 761px) and (max-height: 740px) {
    .block-container { padding-bottom: 1rem; }
    .st-key-terrain_upload ol.as-upload-steps { margin-top: 1.2rem; }
    .as-step-number { width: 64px; height: 64px; margin-bottom: 14px; font-size: 22px; }
    .as-upload-steps::before,.as-upload-steps::after { top: 31px; }
}
@media (prefers-reduced-motion: reduce) { .as-upload-steps::after { animation: none; background-position: center; } }
.st-key-nav_cases button[kind] p { white-space: normal; line-height: 1.4; font-size: .78rem; }
.st-key-nav_guide button[kind] { padding-inline: .5rem; }
.st-key-nav_guide button[kind] p { white-space: nowrap; font-size: .78rem; }
.stApp a.as-source-link { box-sizing: border-box; width: 100%; min-height: 46px; display: flex; align-items: center; justify-content: center; gap: 8px; padding: .5rem; background: rgba(212,175,55,.04); border: 0; border-bottom: 2px solid #a77935; border-radius: 7px 7px 0 0; color: var(--as-gold-300); text-decoration: none; font-size: .78rem; font-weight: 500; white-space: nowrap; }
.stApp a.as-source-link svg { width: 17px; height: 17px; flex: 0 0 17px; }
.stApp a.as-source-link:hover { color: var(--as-gold-300); background: rgba(212,175,55,.1); border-color: var(--as-gold-300); box-shadow: 0 8px 18px -16px #ffe9a8; }
.stApp a.as-source-link:focus-visible { outline: 2px solid var(--as-gold-300); outline-offset: 3px; }
.st-key-nav_workbench_view button[kind] { min-height: 46px; padding-inline: .65rem; background: rgba(212,175,55,.04); border: 0; border-bottom: 2px solid #a77935; border-radius: 7px 7px 0 0; color: var(--as-gold-300); font-weight: 500; box-shadow: none; }
.st-key-nav_workbench_view button[kind] p { font-size: .8rem; }
.st-key-nav_workbench_view button[kind]:hover { background: rgba(212,175,55,.1); border-color: var(--as-gold-300); transform: none; }
.st-key-nav_workbench_view button[kind]::after { display: none; }
.st-key-nav_home{position:relative;top:6px}
.st-key-nav_home button[kind]{width:44px;min-height:42px;padding:.5rem;justify-content:center}
.st-key-nav_home button p{position:absolute;width:1px;height:1px;overflow:hidden;clip-path:inset(50%);white-space:nowrap}
.st-key-nav_home button[kind] [data-testid="stIconMaterial"]{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);margin:0;line-height:1}
"""
