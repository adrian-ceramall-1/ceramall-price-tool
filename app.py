import io
import json
import os
import re
import unicodedata
import html as html_lib

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image
from playwright.sync_api import sync_playwright


st.set_page_config(page_title="Ceramall Price Tool", layout="wide")

st.title("Ceramall Price Tool")
st.write("Introdu un link de produs Ceramall si generam price tag PDF / PNG pentru print.")


COUNTRY_EMOJIS = {
    "uniunea europeana": "🇪🇺",
    "ue": "🇪🇺",
    "eu": "🇪🇺",
    "european union": "🇪🇺",
    "romania": "🇷🇴",
    "italia": "🇮🇹",
    "italy": "🇮🇹",
    "spania": "🇪🇸",
    "spain": "🇪🇸",
    "turcia": "🇹🇷",
    "turkey": "🇹🇷",
    "india": "🇮🇳",
    "polonia": "🇵🇱",
    "poland": "🇵🇱",
    "china": "🇨🇳",
    "germania": "🇩🇪",
    "germany": "🇩🇪",
    "franta": "🇫🇷",
    "france": "🇫🇷",
    "portugalia": "🇵🇹",
    "portugal": "🇵🇹",
    "bulgaria": "🇧🇬",
    "ucraina": "🇺🇦",
    "ukraine": "🇺🇦",
}


def clean_text(value):
    if not value:
        return ""
    value = str(value).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalize_key(value):
    value = clean_text(value).lower()
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return value


def escape(value):
    return html_lib.escape(clean_text(value))


def normalize_price(value):
    value = clean_text(value)
    value = value.replace(".", ",")
    return value


def is_yes(value):
    value = normalize_key(value)
    return value in ["da", "yes", "true", "1"]


def country_flag_html(country):
    emoji = COUNTRY_EMOJIS.get(normalize_key(country), "")
    if not emoji:
        return ""
    return f'<span class="emoji flag-emoji">{emoji}</span>'


def find_product_in_json(data):
    if isinstance(data, dict):
        product_type = data.get("@type")

        if product_type == "Product":
            return data

        if isinstance(product_type, list) and "Product" in product_type:
            return data

        if "@graph" in data:
            return find_product_in_json(data["@graph"])

        for item in data.values():
            found = find_product_in_json(item)
            if found:
                return found

    if isinstance(data, list):
        for item in data:
            found = find_product_in_json(item)
            if found:
                return found

    return {}


def extract_json_ld_product(soup):
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string or "")
        except Exception:
            continue

        product = find_product_in_json(data)
        if product:
            return product

    return {}


def get_lines(soup):
    text = soup.get_text("\n")
    lines = []

    for line in text.splitlines():
        line = clean_text(line)
        if line:
            lines.append(line)

    return lines


def get_spec_from_lines(lines, labels):
    if isinstance(labels, str):
        labels = [labels]

    normalized_labels = [normalize_key(label) for label in labels]

    for index, line in enumerate(lines):
        line_key = normalize_key(line)

        for label, label_key in zip(labels, normalized_labels):
            if line_key == label_key and index + 1 < len(lines):
                return clean_text(lines[index + 1])

            if line_key.startswith(label_key + " "):
                return clean_text(line[len(label):])

    return ""


def extract_prices(page_text, product_json):
    product_area = page_text.split("Produse similare")[0]

    special_match = re.search(
        r"Pre[tț]\s*special\s+([0-9]+(?:[.,][0-9]{1,2})?)\s*lei",
        product_area,
        re.IGNORECASE,
    )

    standard_match = re.search(
        r"Pre[tț]\s*standard\s+([0-9]+(?:[.,][0-9]{1,2})?)\s*lei",
        product_area,
        re.IGNORECASE,
    )

    current_price = ""
    old_price = ""

    if special_match:
        current_price = normalize_price(special_match.group(1))

    if standard_match:
        old_price = normalize_price(standard_match.group(1))

    if not current_price:
        offers = product_json.get("offers", {})
        if isinstance(offers, list):
            offers = offers[0] if offers else {}

        if isinstance(offers, dict):
            current_price = normalize_price(
                offers.get("price")
                or offers.get("lowPrice")
                or offers.get("highPrice")
                or ""
            )

    return current_price, old_price


def clean_display_name(name, sku):
    name = clean_text(name)

    if sku:
        name = re.sub(r"^Gresie\s+" + re.escape(sku) + r"\s+", "", name, flags=re.IGNORECASE)
        name = re.sub(r"^Faianta\s+" + re.escape(sku) + r"\s+", "", name, flags=re.IGNORECASE)
        name = re.sub(r"^Faian[tț][aă]\s+" + re.escape(sku) + r"\s+", "", name, flags=re.IGNORECASE)

    return clean_text(name)


def extract_product_data(product_url):
    headers = {
        "User-Agent": "Mozilla/5.0"
    }

    response = requests.get(product_url, headers=headers, timeout=20)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "lxml")
    product_json = extract_json_ld_product(soup)

    lines = get_lines(soup)
    page_text = clean_text(soup.get_text(" "))

    h1 = soup.find("h1")
    name = clean_text(h1.get_text()) if h1 else ""
    if not name:
        name = clean_text(product_json.get("name", ""))

    sku = get_spec_from_lines(lines, ["Cod produs", "SKU"])
    if not sku:
        sku = clean_text(product_json.get("sku", ""))

    dimension = (
        get_spec_from_lines(lines, ["Marime exacta", "Mărime exactă"])
        or get_spec_from_lines(lines, ["Marime generala", "Mărime generală"])
    )

    thickness = get_spec_from_lines(lines, ["Grosime"])

    porcelain = get_spec_from_lines(
        lines,
        [
            "Portelanata",
            "Porțelanată",
            "Portelanat",
            "Porțelanat",
            "Porcelanat",
            "Porcelanata",
        ],
    )

    country = get_spec_from_lines(
        lines,
        [
            "Tara de origine",
            "Țara de origine",
            "Tara origine",
            "Origine",
        ],
    )

    current_price, old_price = extract_prices(page_text, product_json)
    display_name = clean_display_name(name, sku)

    return {
        "name": display_name,
        "full_name": name,
        "sku": sku,
        "dimension": dimension,
        "thickness": thickness,
        "current_price": current_price,
        "old_price": old_price,
        "quality": "1",
        "porcelain": "Da" if is_yes(porcelain) else "Nu",
        "country": country,
        "source_url": product_url,
    }


def launch_browser(playwright):
    launch_kwargs = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage"],
    }

    if os.path.exists("/usr/bin/chromium"):
        launch_kwargs["executable_path"] = "/usr/bin/chromium"

    return playwright.chromium.launch(**launch_kwargs)


def build_price_template(data, tag_type, preview=False):
    name_clean = clean_text(data.get("name", ""))
    name = escape(name_clean)
    sku = escape(data.get("sku", ""))
    dimension = escape(data.get("dimension", "")).replace(" cm", "")
    thickness = escape(data.get("thickness", "")).replace(" mm", "")
    current_price = escape(data.get("current_price", ""))
    old_price = escape(data.get("old_price", ""))
    quality = escape(data.get("quality", "1"))
    country_raw = clean_text(data.get("country", ""))
    country = escape(country_raw)

    porcelain_value = clean_text(data.get("porcelain", "Nu"))
    show_porcelain = is_yes(porcelain_value)

    country_flag = country_flag_html(country_raw)

    if tag_type == "Outlet":
        top_class = "top outlet"
        title = "OUTLET"
        show_gift = False
    else:
        top_class = "top special"
        title = "Ofertă specială"
        show_gift = True

    old_price_html = ""
    if old_price:
        old_price_html = f"""
            <div class="old-price">
                <div class="old-number">{old_price}</div>
                <div class="old-line"></div>
                <div class="old-label">preț vechi</div>
            </div>
        """

    extra_items = ""

    if country:
        extra_items += f"""
            <div class="extra-item">
                <div class="extra-label">țara de origine</div>
                <div class="extra-value">{country_flag}{country}</div>
            </div>
        """

    if show_porcelain:
        extra_items += """
            <div class="extra-item">
                <div class="extra-label">tip produs</div>
                <div class="extra-value">Porțelanată</div>
            </div>
        """

    extras_html = ""
    if extra_items:
        extras_html = f"""
            <div class="extras">
                {extra_items}
            </div>
        """

    gift_html = ""
    if show_gift:
        gift_html = """
            <div class="gift-box">
                <div class="gift-text">
                    5m&sup2; = 1 sac adeziv <span>CADOU!</span> <span class="emoji gift-emoji">🎁</span>
                </div>
            </div>
        """

    name_class = "name"
    if len(name_clean) > 28:
        name_class += " small"
    if len(name_clean) > 42:
        name_class += " xsmall"
    if len(name_clean) > 60:
        name_class += " xxsmall"

    body_class = "preview-body" if preview else "pdf-body"
    scale_wrap_start = '<div class="preview-scale">' if preview else ""
    scale_wrap_end = "</div>" if preview else ""

    html = f"""
    <!doctype html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            @page {{
                size: 90mm auto;
                margin: 0;
            }}

            * {{
                box-sizing: border-box;
            }}

            html {{
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}

            html, body {{
                margin: 0;
                padding: 0;
                font-family: Arial, Helvetica, sans-serif;
                color: #111;
            }}

            body.pdf-body {{
                width: 90mm;
                background: white;
            }}

            body.preview-body {{
                background: transparent;
                padding: 0;
                overflow: auto;
            }}

            .preview-scale {{
                zoom: 2.35;
                width: 90mm;
                min-height: 90mm;
            }}

            .sheet {{
                width: 90mm;
                min-height: 90mm;
                background: white;
                overflow: visible;
            }}

            .emoji {{
                font-family: "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji", sans-serif;
                font-style: normal !important;
                font-weight: 400 !important;
                line-height: 1;
                display: inline-block;
            }}

            .flag-emoji {{
                font-size: 10pt;
                margin-right: 1mm;
                vertical-align: -0.4mm;
            }}

            .gift-emoji {{
                font-size: 11pt;
                vertical-align: -0.4mm;
            }}

            .top {{
                height: 37mm;
                padding: 7mm 9mm 5mm 9mm;
            }}

            .top.special {{
                background: #82d84b;
            }}

            .top.outlet {{
                background: #ff5b00;
            }}

            .offer {{
                color: white;
                font-size: 14pt;
                font-weight: 900;
                margin-bottom: 4mm;
            }}

            .price-row {{
                display: flex;
                align-items: flex-start;
                justify-content: space-between;
                gap: 4mm;
            }}

            .price-main {{
                display: flex;
                align-items: flex-start;
                gap: 2mm;
            }}

            .price-number {{
                font-size: 42pt;
                line-height: 0.85;
                font-weight: 900;
                letter-spacing: -2px;
            }}

            .price-unit {{
                font-size: 15pt;
                line-height: 0.95;
                font-weight: 900;
                padding-top: 1mm;
            }}

            .old-price {{
                text-align: center;
                min-width: 17mm;
                padding-top: 0mm;
                margin-top: 0.8mm;
            }}

            .old-number {{
                font-size: 15pt;
                line-height: 1;
                font-weight: 900;
                text-decoration: line-through;
            }}

            .old-line {{
                height: 1mm;
                background: #222;
                margin: 0.8mm 0 1mm 0;
            }}

            .old-label {{
                color: white;
                font-size: 8.2pt;
                line-height: 1;
                font-weight: 900;
            }}

            .bottom {{
                padding: 8mm 11mm 8mm 11mm;
            }}

            .label {{
                font-size: 7.5pt;
                font-weight: 900;
                color: #222;
                margin-bottom: 1mm;
            }}

            .name {{
                font-size: 13pt;
                font-weight: 900;
                font-style: italic;
                border-bottom: 0.7mm solid #222;
                padding-bottom: 2mm;
                margin-bottom: 5mm;
                white-space: normal;
                overflow: visible;
                text-overflow: clip;
                word-break: break-word;
                overflow-wrap: anywhere;
                line-height: 1.08;
            }}

            .name.small {{
                font-size: 12pt;
            }}

            .name.xsmall {{
                font-size: 10.8pt;
            }}

            .name.xxsmall {{
                font-size: 9.8pt;
            }}

            .grid {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 4mm 9mm;
            }}

            .value {{
                font-size: 13pt;
                font-weight: 400;
                line-height: 1.1;
            }}

            .extras {{
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 3mm 6mm;
                margin-top: 5mm;
                border-top: 0.4mm solid #d5d5d5;
                padding-top: 3mm;
            }}

            .extra-label {{
                font-size: 6.8pt;
                font-weight: 900;
                color: #333;
                margin-bottom: 0.8mm;
            }}

            .extra-value {{
                font-size: 9.5pt;
                font-weight: 800;
                line-height: 1.15;
            }}

            .gift-box {{
                margin-top: 5mm;
                border-top: 0.4mm solid #d5d5d5;
                padding-top: 3.5mm;
            }}

            .gift-text {{
                display: flex;
                align-items: center;
                gap: 1.5mm;
                font-size: 9pt;
                line-height: 1.1;
                font-weight: 900;
                color: #111;
                white-space: nowrap;
            }}

            .gift-text span {{
                font-size: 9.5pt;
                font-weight: 1000;
            }}
        </style>
    </head>
    <body class="{body_class}">
        {scale_wrap_start}
        <div class="sheet">
            <div class="{top_class}">
                <div class="offer">{title}</div>

                <div class="price-row">
                    <div class="price-main">
                        <div class="price-number">{current_price}</div>
                        <div class="price-unit">lei<br>/m&sup2;</div>
                    </div>

                    {old_price_html}
                </div>
            </div>

            <div class="bottom">
                <div class="label">denumire</div>
                <div class="{name_class}">{name}</div>

                <div class="grid">
                    <div>
                        <div class="label">dimensiune (cm)</div>
                        <div class="value">{dimension}</div>
                    </div>

                    <div>
                        <div class="label">grosime (mm)</div>
                        <div class="value">{thickness}</div>
                    </div>

                    <div>
                        <div class="label">cod produs</div>
                        <div class="value">{sku}</div>
                    </div>

                    <div>
                        <div class="label">calitate</div>
                        <div class="value">{quality}</div>
                    </div>
                </div>

                {extras_html}

                {gift_html}
            </div>
        </div>
        {scale_wrap_end}
    </body>
    </html>
    """

    return html


def html_to_png_bytes(html, dpi=300):
    with sync_playwright() as p:
        browser = launch_browser(p)
        page = browser.new_page(
            viewport={"width": 600, "height": 2600},
            device_scale_factor=4,
        )
        page.set_content(html, wait_until="networkidle")

        raw_png = page.locator(".sheet").screenshot(type="png")

        browser.close()

    img = Image.open(io.BytesIO(raw_png)).convert("RGB")

    target_width_px = round(90 / 25.4 * dpi)
    ratio = target_width_px / img.width
    target_height_px = round(img.height * ratio)

    img = img.resize((target_width_px, target_height_px), Image.LANCZOS)

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", dpi=(dpi, dpi), optimize=True)

    return buffer.getvalue()


def png_bytes_to_pdf_bytes(png_bytes, dpi=300):
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buffer = io.BytesIO()
    img.save(buffer, format="PDF", resolution=dpi)
    return buffer.getvalue()


def html_to_pdf_bytes(html, dpi=300):
    png_bytes = html_to_png_bytes(html, dpi=dpi)
    return png_bytes_to_pdf_bytes(png_bytes, dpi=dpi)


if "product_data" not in st.session_state:
    st.session_state.product_data = None

if "pdf_bytes" not in st.session_state:
    st.session_state.pdf_bytes = None

if "png_bytes" not in st.session_state:
    st.session_state.png_bytes = None

if "pdf_name" not in st.session_state:
    st.session_state.pdf_name = "price-tag.pdf"

if "png_name" not in st.session_state:
    st.session_state.png_name = "price-tag.png"


url = st.text_input(
    "Link produs",
    value="https://www.ceramall.ro/31770-light-grey-45x45-mat-z.html"
)

if st.button("Extrage datele"):
    if not url:
        st.warning("Pune mai intai un link de produs.")
    else:
        try:
            st.session_state.product_data = extract_product_data(url)
            st.session_state.pdf_bytes = None
            st.session_state.png_bytes = None
            st.success("Date extrase cu succes.")
        except Exception as e:
            st.error(f"A aparut o eroare: {e}")


if st.session_state.product_data:
    data = st.session_state.product_data

    st.divider()
    st.subheader("Date pentru price tag")

    col1, col2 = st.columns(2)

    with col1:
        tag_type = st.selectbox(
            "Tip price tag",
            ["Ofertă specială", "Outlet"],
        )

        name = st.text_input("Denumire", value=data.get("name", ""))
        sku = st.text_input("Cod produs / SKU", value=data.get("sku", ""))
        dimension = st.text_input("Dimensiune", value=data.get("dimension", ""))
        thickness = st.text_input("Grosime", value=data.get("thickness", ""))

    with col2:
        current_price = st.text_input("Pret actual", value=data.get("current_price", ""))
        old_price = st.text_input("Pret vechi", value=data.get("old_price", ""))
        quality = st.text_input("Calitate", value=data.get("quality", "1"))

        porcelain = st.selectbox(
            "Portelanata",
            ["Nu", "Da"],
            index=1 if data.get("porcelain") == "Da" else 0,
        )

        country = st.text_input("Tara de origine", value=data.get("country", ""))

    final_data = {
        "name": name,
        "sku": sku,
        "dimension": dimension,
        "thickness": thickness,
        "current_price": current_price,
        "old_price": old_price,
        "quality": quality,
        "porcelain": porcelain,
        "country": country,
    }

    st.divider()
    st.subheader("Preview price tag")

    preview_html = build_price_template(final_data, tag_type, preview=True)
    components.html(preview_html, height=1700, scrolling=True)

    render_html = build_price_template(final_data, tag_type, preview=False)

    col_a, col_b, col_c = st.columns([1, 1, 2])

    with col_a:
        if st.button("Genereaza PDF"):
            try:
                with st.spinner("Generez PDF..."):
                    st.session_state.pdf_bytes = html_to_pdf_bytes(render_html, dpi=300)
                    safe_sku = sku or "produs"
                    safe_type = "outlet" if tag_type == "Outlet" else "oferta-speciala"
                    st.session_state.pdf_name = f"pretar-{safe_type}-{safe_sku}.pdf"
                st.success("PDF generat.")
            except Exception as e:
                st.error(f"Nu am putut genera PDF-ul: {e}")

    with col_b:
        if st.button("Genereaza PNG print"):
            try:
                with st.spinner("Generez PNG 300 DPI..."):
                    st.session_state.png_bytes = html_to_png_bytes(render_html, dpi=300)
                    safe_sku = sku or "produs"
                    safe_type = "outlet" if tag_type == "Outlet" else "oferta-speciala"
                    st.session_state.png_name = f"pretar-{safe_type}-{safe_sku}-300dpi.png"
                st.success("PNG generat.")
            except Exception as e:
                st.error(f"Nu am putut genera PNG-ul: {e}")

    with col_c:
        if st.session_state.pdf_bytes:
            st.download_button(
                label="Descarca PDF",
                data=st.session_state.pdf_bytes,
                file_name=st.session_state.pdf_name,
                mime="application/pdf",
            )

        if st.session_state.png_bytes:
            st.download_button(
                label="Descarca PNG 300 DPI",
                data=st.session_state.png_bytes,
                file_name=st.session_state.png_name,
                mime="image/png",
            )

    with st.expander("Date brute extrase"):
        st.json(data)
