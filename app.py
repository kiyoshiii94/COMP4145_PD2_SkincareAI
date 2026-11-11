import base64
import json
import os
import re
import sqlite3
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

import requests
import streamlit as st


ENDPOINT_URL = "https://genai.hkbu.edu.hk/api/v1/chat/completions"
MODEL_OPTIONS = ["gpt-6-luna", "gpt-4o"]
DB_PATH = "dermalytics.db"

CATALOGUE = [
    {"name": "Cloud Veil Gentle Cleanser", "step": "Cleanser", "active": "Ceramides", "price": 168, "sensitive": True, "time": "AM/PM", "asset": "assets/cleanser.png"},
    {"name": "Clear Balance BHA Cleanser", "step": "Cleanser", "active": "Salicylic Acid BHA", "price": 188, "sensitive": False, "time": "PM", "asset": "assets/cleanser.png"},
    {"name": "Aqua Plump HA Serum", "step": "Serum", "active": "Hyaluronic Acid", "price": 238, "sensitive": True, "time": "AM/PM", "asset": "assets/serum-ha.png"},
    {"name": "Calm Repair Cica Serum", "step": "Serum", "active": "Centella Asiatica (Cica)", "price": 258, "sensitive": True, "time": "AM/PM", "asset": "assets/serum-cica.png"},
    {"name": "Bright Shield Vitamin C", "step": "Serum", "active": "Vitamin C", "price": 278, "sensitive": False, "time": "AM", "asset": "assets/serum-vitamin-c.png"},
    {"name": "Renewal Retinal Serum", "step": "Serum", "active": "Retinal", "price": 298, "sensitive": False, "time": "PM", "asset": "assets/retinal.png"},
    {"name": "Barrier Cloud Moisturiser", "step": "Moisturiser", "active": "Ceramides", "price": 198, "sensitive": True, "time": "AM/PM", "asset": "assets/moisturiser.png"},
    {"name": "Azelaic Calm Cream", "step": "Moisturiser", "active": "Azelaic Acid", "price": 248, "sensitive": True, "time": "PM", "asset": "assets/moisturiser.png"},
    {"name": "Daily Mineral Defence SPF50", "step": "Broad-Spectrum SPF", "active": "Zinc Oxide", "price": 218, "sensitive": True, "time": "AM", "asset": "assets/sunscreen.png"},
    {"name": "Niacinamide Pore Veil", "step": "Serum", "active": "Niacinamide", "price": 228, "sensitive": True, "time": "AM/PM", "asset": "assets/serum-niacinamide.png"},
]


def demo_result() -> dict[str, Any]:
    return {
        "skin_cleanliness_score": 6.8,
        "skin_cleanliness_review": "Generally clear, with mild congestion visible through the T-zone.",
        "skin_quality_score": 6.1,
        "skin_quality_review": "Balanced overall, though texture and hydration can be improved with consistent barrier care.",
        "estimated_age_range": "24–29 years",
        "overall_condition_summary": "The image-based review suggests mildly dehydrated skin with moderate pore congestion and subtle texture variation. A gentle barrier-first routine and daily SPF may support a more even, comfortable complexion.",
        "hydration": 5.8,
        "pores": 6.2,
        "redness": 7.8,
        "texture": 6.4,
    }


def initialise_database() -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS scan_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL,
                scan_date TEXT NOT NULL, cleanliness_kpi REAL NOT NULL,
                quality_kpi REAL NOT NULL, hydration REAL NOT NULL,
                pores REAL NOT NULL, redness REAL NOT NULL, texture REAL NOT NULL,
                estimated_age TEXT, matched_ingredients TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS saved_routines (
                username TEXT PRIMARY KEY, updated_at TEXT NOT NULL,
                am_routine TEXT NOT NULL, pm_routine TEXT NOT NULL,
                discounted_total_hkd REAL NOT NULL
            )"""
        )
        existing = connection.execute(
            "SELECT COUNT(*) FROM scan_history WHERE username = ?", ("demo_customer",)
        ).fetchone()[0]
        if existing == 0:
            baseline = [
                (6.2, 5.5, 4.9, 5.4, 6.1, 5.2),
                (6.8, 5.9, 5.3, 5.8, 6.5, 5.7),
                (7.4, 6.5, 5.6, 6.1, 7.0, 6.1),
                (8.0, 7.0, 6.2, 6.7, 7.6, 6.8),
            ]
            for weeks_ago, values in zip(range(3, -1, -1), baseline):
                connection.execute(
                    """INSERT INTO scan_history
                    (username, scan_date, cleanliness_kpi, quality_kpi, hydration,
                     pores, redness, texture, estimated_age, matched_ingredients)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "demo_customer",
                        (date.today() - timedelta(days=weeks_ago * 7)).isoformat(),
                        *values,
                        "24–29 years",
                        json.dumps(["Hyaluronic Acid", "Niacinamide"]),
                    ),
                )
        connection.execute(
            """INSERT OR IGNORE INTO saved_routines
            (username, updated_at, am_routine, pm_routine, discounted_total_hkd)
            VALUES (?, ?, ?, ?, ?)""",
            (
                "demo_customer",
                datetime.now().isoformat(timespec="seconds"),
                json.dumps(["Cloud Veil Gentle Cleanser", "Aqua Plump HA Serum", "Daily Mineral Defence SPF50"]),
                json.dumps(["Cloud Veil Gentle Cleanser", "Renewal Retinal Serum", "Barrier Cloud Moisturiser"]),
                1094.8,
            ),
        )


def load_scans(username: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(DB_PATH) as connection:
        return connection.execute(
            """SELECT scan_date, cleanliness_kpi, quality_kpi, hydration, pores,
            redness, texture, estimated_age, matched_ingredients
            FROM scan_history WHERE username = ? ORDER BY scan_date""",
            (username,),
        ).fetchall()


def load_saved_routine(username: str) -> tuple[list[str], list[str], float] | None:
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT am_routine, pm_routine, discounted_total_hkd FROM saved_routines WHERE username = ?",
            (username,),
        ).fetchone()
    if not row:
        return None
    return json.loads(row[0]), json.loads(row[1]), float(row[2])


def save_scan(username: str, result: dict[str, Any]) -> None:
    matched = matched_ingredients(result)
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """INSERT INTO scan_history
            (username, scan_date, cleanliness_kpi, quality_kpi, hydration, pores,
             redness, texture, estimated_age, matched_ingredients)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                username,
                date.today().isoformat(),
                score(result, "skin_cleanliness_score"),
                score(result, "skin_quality_score"),
                score(result, "hydration"),
                score(result, "pores"),
                score(result, "redness"),
                score(result, "texture"),
                str(result.get("estimated_age_range", "—")),
                json.dumps(matched),
            ),
        )


def save_routine(username: str, am: list[str], pm: list[str], total: float) -> None:
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """INSERT INTO saved_routines
            (username, updated_at, am_routine, pm_routine, discounted_total_hkd)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET updated_at=excluded.updated_at,
            am_routine=excluded.am_routine, pm_routine=excluded.pm_routine,
            discounted_total_hkd=excluded.discounted_total_hkd""",
            (username, datetime.now().isoformat(timespec="seconds"), json.dumps(am), json.dumps(pm), total),
        )


def image_data_url(image_bytes: bytes, mime_type: str) -> str:
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('utf-8')}"


def parse_response(response_body: dict[str, Any]) -> dict[str, Any]:
    try:
        content = response_body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("The API response did not contain message content.") from error
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict))
    if not isinstance(content, str):
        raise ValueError("The API returned an unsupported content format.")
    content = content.strip()
    if content.startswith("```"):
        content = content.removeprefix("```json").removeprefix("```").strip().removesuffix("```").strip()
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("The API returned an invalid JSON object.")
    return parsed


def normalise_analysis_result(response_body: dict[str, Any]) -> dict[str, Any]:
    aliases = {
        "skin_cleanliness_score": ("skin cleanliness", "cleanliness", "cleanliness score"),
        "skin_quality_score": ("skin quality", "quality", "quality score"),
        "hydration": ("hydration",),
        "pores": ("pores", "pore congestion"),
        "redness": ("redness", "redness sensitivity"),
        "texture": ("texture", "pigmentation texture"),
        "estimated_age_range": ("estimated age range", "estimated age", "age range"),
        "overall_condition_summary": ("overall condition summary", "condition summary", "summary"),
    }
    score_keys = {"skin_cleanliness_score", "skin_quality_score", "hydration", "pores", "redness", "texture"}
    normalised_aliases = {
        canonical: {re.sub(r"[^a-z0-9]", "", alias) for alias in possible_keys}
        for canonical, possible_keys in aliases.items()
    }
    result: dict[str, Any] = dict(response_body)

    def extract_metric_value(value: Any) -> Any:
        if isinstance(value, dict):
            for key in ("score", "value", "rating", "numeric_score", "score_10", "result"):
                if key in value:
                    return extract_metric_value(value[key])
        if isinstance(value, list):
            for item in value:
                extracted = extract_metric_value(item)
                if extracted is not None:
                    return extracted
        return value

    def has_numeric_score(value: Any) -> bool:
        value = extract_metric_value(value)
        if isinstance(value, (int, float)):
            return True
        return isinstance(value, str) and re.search(r"\d+(?:\.\d+)?", value) is not None

    def visit(value: Any, label: str = "") -> None:
        if isinstance(value, dict):
            item_label = label
            label_value = None
            for key, nested in value.items():
                key_name = re.sub(r"[^a-z0-9]", "", str(key).lower())
                for canonical, names in normalised_aliases.items():
                    if key_name in names or key_name.removesuffix("score") in names:
                        candidate = extract_metric_value(nested)
                        if canonical not in score_keys or has_numeric_score(candidate):
                            result[canonical] = candidate
                if key_name in {"name", "metric", "category", "label"} and isinstance(nested, str):
                    item_label = nested
                if key_name in {"score", "value", "rating", "numericscore", "score10", "result"}:
                    label_value = nested
                visit(nested, str(key))
            label_name = re.sub(r"[^a-z0-9]", "", item_label.lower())
            for canonical, names in normalised_aliases.items():
                if label_name in names or label_name.removesuffix("score") in names:
                    metric_value = extract_metric_value(value)
                    if metric_value is not None:
                        if canonical not in score_keys or has_numeric_score(metric_value):
                            result[canonical] = metric_value
        elif isinstance(value, list):
            for item in value:
                visit(item, label)

    visit(response_body)
    missing = [
        key for key in aliases
        if key not in result or (key in score_keys and not has_numeric_score(result[key]))
    ]
    if missing:
        raise ValueError(f"The API response is missing required metrics: {', '.join(missing)}.")
    return result


def request_analysis(api_key: str, model: str, image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    prompt = """Review this facial image for a cosmetic, non-medical skin quality check.
Return only JSON with keys: skin_cleanliness_score, skin_cleanliness_review,
skin_quality_score, skin_quality_review, estimated_age_range, overall_condition_summary,
hydration, pores, redness, texture. Scores must be numbers from 0 to 10. Use neutral,
observable language and say the result is image-based and not medical advice."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a careful professional skincare assistant."},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url(image_bytes, mime_type)}},
            ]},
        ],
        "temperature": 0.2,
    }
    response = requests.post(
        ENDPOINT_URL,
        headers={"api-key": api_key, "Authorization": "Bearer " + api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    return normalise_analysis_result(parse_response(response.json()))


def extract_score_value(value: Any) -> Any:
    if isinstance(value, dict):
        for name in ("score", "value", "rating", "numeric_score", "score_10", "result"):
            if name in value:
                return extract_score_value(value[name])
        return None
    if isinstance(value, list):
        for item in value:
            extracted = extract_score_value(item)
            if extracted is not None:
                return extracted
        return None
    return value


def score(result: dict[str, Any], key: str) -> float:
    try:
        value = extract_score_value(result.get(key))
        if isinstance(value, str):
            match = re.search(r"\d+(?:\.\d+)?", value)
            if not match:
                return 0.0
            value = match.group()
        return max(0.0, min(10.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def matched_ingredients(result: dict[str, Any]) -> list[str]:
    matches = []
    if score(result, "hydration") < 7.5:
        matches.append("Hyaluronic Acid / Ceramides")
    if score(result, "pores") < 7.5 or score(result, "skin_cleanliness_score") < 7.5:
        matches.append("Salicylic Acid BHA / Niacinamide")
    if score(result, "redness") < 7.5:
        matches.append("Centella Asiatica / Azelaic Acid")
    if score(result, "texture") < 7.5 or score(result, "skin_quality_score") < 7.5:
        matches.append("Vitamin C / Retinal")
    return matches


def product(name: str) -> dict[str, Any]:
    return next(item for item in CATALOGUE if item["name"] == name)


def render_product_thumbnail(item: dict[str, Any]) -> None:
    asset_path = item["asset"]
    if os.path.exists(asset_path):
        st.image(asset_path, use_container_width=True)
        return

    colours = {
        "Cleanser": ("#dceff2", "#4d9eae"),
        "Serum": ("#e5e0f3", "#7869a8"),
        "Moisturiser": ("#e5f1e8", "#5b9a79"),
        "Broad-Spectrum SPF": ("#f5ead5", "#c18a43"),
    }
    background, accent = colours.get(item["step"], ("#e8eef0", "#66838a"))
    if item["step"] == "Cleanser":
        shape = '<rect x="83" y="46" width="74" height="112" rx="14"/><path d="M101 46V30h38v16m-19-16v-10h35v10"/>'
    elif item["step"] == "Serum":
        shape = '<rect x="88" y="57" width="64" height="101" rx="18"/><path d="M106 57V34h28v23m-14-23V17h9"/>'
    elif item["step"] == "Moisturiser":
        shape = '<path d="M65 70h110l-9 88H74z"/><rect x="57" y="52" width="126" height="22" rx="8"/>'
    else:
        shape = '<path d="M78 42h84l-9 116H87z"/><path d="M78 42h84l-9-18H87z"/>'
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="280" height="150" viewBox="0 0 240 180">
      <rect width="240" height="180" rx="16" fill="{background}"/>
      <ellipse cx="120" cy="162" rx="68" ry="8" fill="#b9c9cc" opacity=".45"/>
      <g fill="{accent}" stroke="#ffffff" stroke-width="3">{shape}</g>
      <rect x="72" y="116" width="96" height="25" rx="5" fill="#ffffff" opacity=".9"/>
      <text x="120" y="132" text-anchor="middle" fill="#36565d" font-size="9" font-family="Arial" font-weight="700">{escape(item["active"][:22])}</text>
      <text x="120" y="22" text-anchor="middle" fill="#5f787e" font-size="10" font-family="Arial">{escape(item["step"])}</text>
    </svg>
    """
    st.markdown(svg, unsafe_allow_html=True)


def conflict_message(item: dict[str, Any], routine: str, target: list[str]) -> str | None:
    if routine == "AM" and item["active"] == "Retinal":
        return "Retinal is PM only; keep it out of your morning routine."
    active_ingredients = [product(name)["active"] for name in target]
    if routine == "PM" and item["active"] == "Salicylic Acid BHA" and "Retinal" in active_ingredients:
        return "Avoid combining Salicylic Acid BHA and Retinal in the same PM routine."
    if routine == "PM" and item["active"] == "Retinal" and "Salicylic Acid BHA" in active_ingredients:
        return "Avoid combining Retinal and Salicylic Acid BHA in the same PM routine."
    if routine == "AM" and item["active"] == "Vitamin C":
        return "Vitamin C is AM only and should be paired with SPF."
    return None


def add_to_routine(name: str, routine: str) -> None:
    item = product(name)
    target = st.session_state[f"{routine.lower()}_routine"]
    warning = conflict_message(item, routine, target)
    if warning:
        st.toast(warning, icon="⚠️")
    elif name not in target:
        target.append(name)
        st.toast(f"{item['name']} added to your {routine} routine.", icon="✅")
    else:
        st.toast(f"{item['name']} is already in your {routine} routine.", icon="ℹ️")


def add_button(name: str, routine: str, label: str, key: str) -> None:
    if st.button(label, key=key):
        before = list(st.session_state[f"{routine.lower()}_routine"])
        add_to_routine(name, routine)
        after = st.session_state[f"{routine.lower()}_routine"]
        if after != before:
            st.rerun()


def render_metric(title: str, value: float, key: str) -> None:
    st.markdown(
        f'<div class="metric-card"><div class="metric-heading">{escape(title)}</div>'
        f'<div class="score">{value:.1f}<span class="out-of"> / 10</span></div></div>',
        unsafe_allow_html=True,
    )
    st.progress(value / 10)
    review = {
        "cleanliness": "Mostly clear with manageable congestion visible through the T-zone.",
        "quality": "Balanced appearance with room to improve hydration and texture.",
    }.get(key, "Image-based review available for cosmetic guidance.")
    st.caption(f"Aesthetician's Review: {review}")


def render_diagnosis(result: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">KEY INDICATORS</div>', unsafe_allow_html=True)
    columns = st.columns([1, 1, .9])
    with columns[0]:
        render_metric("Skin Cleanliness KPI", score(result, "skin_cleanliness_score"), "cleanliness")
    with columns[1]:
        render_metric("Skin Quality KPI", score(result, "skin_quality_score"), "quality")
    with columns[2]:
        st.markdown(
            f'<div class="age-card"><div class="metric-heading">ESTIMATED AGE</div>'
            f'<div class="age-value">{escape(str(result.get("estimated_age_range", "—")))}</div>'
            '<div class="age-note">Visual estimate only</div></div>',
            unsafe_allow_html=True,
        )
    summary = str(result.get("overall_condition_summary", "No summary returned."))
    summary = summary.replace("This is not medical advice.", "").strip()
    st.markdown('<div class="report-card"><div class="report-title">Professional Skincare Report</div>'
                '<div class="report-rule"></div><div class="report-subtitle">OVERALL CONDITION SUMMARY</div>'
                f'<p>{escape(summary)}</p>'
                '<div class="side-note">Side note: This is an image-based cosmetic estimate, not medical advice.</div></div>',
                unsafe_allow_html=True)


def render_breakdown(result: dict[str, Any]) -> None:
    st.markdown("#### Sub-Metric Breakdown")
    metrics = [("Hydration", "hydration"), ("Pore Congestion", "pores"),
               ("Redness & Sensitivity", "redness"), ("Pigmentation & Texture", "texture")]
    columns = st.columns(4)
    for column, (title, key) in zip(columns, metrics):
        with column:
            render_metric(title, score(result, key), key)


def render_matcher(result: dict[str, Any]) -> None:
    st.markdown("#### Active Ingredient Matcher")
    rules = [
        ("Hydration", "hydration", "Hyaluronic Acid or Ceramides", "AM & PM safe", "Supports water retention and barrier comfort."),
        ("Pore Congestion / Cleanliness", "pores", "Salicylic Acid BHA or Niacinamide", "BHA: PM only · Niacinamide: AM & PM", "Helps refine congestion while respecting timing."),
        ("Redness & Sensitivity", "redness", "Centella Asiatica (Cica) + Azelaic Acid", "AM & PM safe", "Soothing options for a calmer-looking complexion."),
        ("Texture / Skin Quality", "texture", "Vitamin C + Retinal", "Vitamin C: AM · Retinal: PM", "Separate these timings; always use SPF with Vitamin C."),
    ]
    priority_matches = []
    for label, key, ingredients, timing, reason in rules:
        if score(result, key) < 7.5:
            priority_matches.append((label, ingredients, timing, reason))
    if priority_matches:
        for label, ingredients, timing, reason in priority_matches:
            st.markdown(
                f'<div class="match-row"><strong>{escape(label)}</strong> · {escape(ingredients)}'
                f'<span class="badge">{escape(timing)}</span><br><small>{escape(reason)}</small></div>',
                unsafe_allow_html=True,
            )
    else:
        st.success("No priority concerns detected. These ingredients can help maintain the current skin condition.")
        for label, _, ingredients, timing, reason in rules:
            st.markdown(
                f'<div class="match-row"><strong>{escape(label)} maintenance</strong> · {escape(ingredients)}'
                f'<span class="badge">{escape(timing)}</span><br><small>{escape(reason)}</small></div>',
                unsafe_allow_html=True,
            )
    st.warning("AM/PM conflict guard: do not mix Retinal and Salicylic Acid BHA in one PM routine. Separate Vitamin C (AM) from Retinal (PM).")


def render_shelf(result: dict[str, Any]) -> None:
    st.markdown("#### Matched Products for Your Skin")
    needed = matched_ingredients(result)
    matches = [item for item in CATALOGUE if any(token.lower() in item["active"].lower() for token in needed for token in token.split(" / "))]
    if not matches:
        matches = CATALOGUE[:3]
    with st.expander("Open matched product shelf", expanded=True):
        columns = st.columns(3)
        for column, item in zip(columns * ((len(matches) + 2) // 3), matches):
            with column:
                render_product_thumbnail(item)
                st.markdown(f"**{item['name']}**  \n{item['active']} · HK${item['price']}")
                st.caption(f"{item['step']} · {item['time']}")
                am, pm = st.columns(2)
                with am:
                    if item["time"] in ("AM", "AM/PM"):
                        add_button(item["name"], "AM", "+ Add to AM Routine", f"am_{item['name']}")
                with pm:
                    if item["time"] in ("PM", "AM/PM") and item["step"] != "Broad-Spectrum SPF":
                        add_button(item["name"], "PM", "+ Add to PM Routine", f"pm_{item['name']}")


def render_tab_one() -> None:
    result = st.session_state.result
    left, right = st.columns([.9, 1.7], gap="large")
    with left:
        st.markdown('<div class="panel-title">1. Source Capture</div>', unsafe_allow_html=True)
        uploaded = st.file_uploader("Upload a frontal face image", type=["jpg", "jpeg", "png"], key="capture")
        if uploaded:
            from PIL import Image, ImageOps
            frame = ImageOps.fit(Image.open(uploaded), (560, 420), method=Image.Resampling.LANCZOS)
            st.image(frame, caption="Standardised 4:3 capture frame", use_container_width=True)
        clear, analyse = st.columns(2)
        with clear:
            if st.button("Clear Image", use_container_width=True):
                st.session_state.result = None
                st.rerun()
        with analyse:
            clicked = st.button("Analyze Skin", type="primary", use_container_width=True)
        st.markdown('<div class="guidelines"><strong>Capture guidelines</strong><br>• Bright natural neutral lighting<br>• Clean makeup-free face<br>• Face directly forward<br>• Clear focus and minimal shadows</div>', unsafe_allow_html=True)
        if clicked:
            if not uploaded:
                st.warning("Please upload a JPG or PNG face image first.")
            elif not st.session_state.api_key.strip():
                st.session_state.result = demo_result()
                st.session_state.demo_mode = True
                st.info("No API key entered. Demo Mode loaded.")
            else:
                try:
                    st.session_state.result = request_analysis(st.session_state.api_key.strip(), st.session_state.model, uploaded.getvalue(), uploaded.type or "image/jpeg")
                    st.session_state.demo_mode = False
                except (requests.RequestException, ValueError, json.JSONDecodeError) as error:
                    st.session_state.result = None
                    st.session_state.demo_mode = False
                    st.error(f"API analysis failed. No demo result was substituted: {error}")
        result = st.session_state.result
    with right:
        st.markdown('<div class="panel-title">2. Evaluation Results</div>', unsafe_allow_html=True)
        if result:
            if st.session_state.demo_mode:
                st.info("Demo Mode · Sample scan with testable sub-metrics")
            render_diagnosis(result)
        else:
            st.info("Upload a face image and select Analyze Skin to view the report.")
    if result:
        render_breakdown(result)
        render_matcher(result)
        render_shelf(result)
        if st.button("Save This Scan to My Progress", type="secondary"):
            save_scan(st.session_state.username, result)
            st.success("Scan saved to your profile.")


def render_routine_item(name: str, routine: str) -> None:
    item = product(name)
    st.markdown(f'<div class="routine-item"><strong>{item["step"]}</strong><br>{item["name"]}<br><small>{item["active"]} · HK${item["price"]}</small></div>', unsafe_allow_html=True)
    if st.button("Remove", key=f"remove_{routine}_{name}"):
        st.session_state[f"{routine.lower()}_routine"].remove(name)
        st.rerun()


def render_routine_builder() -> None:
    st.markdown("### Dermalytics E-Shop Catalogue")
    budget = st.slider("Max Budget per Product (HKD)", 100, 400, 400, 10)
    sensitive_only = st.toggle("Sensitive / Fragrance-Free Only")
    filtered = [item for item in CATALOGUE if item["price"] <= budget and (not sensitive_only or item["sensitive"])]
    st.caption(f"{len(filtered)} products available")
    columns = st.columns(3)
    for column, item in zip(columns * ((len(filtered) + 2) // 3), filtered):
        with column:
            render_product_thumbnail(item)
            st.markdown(f"**{item['name']}**  \n{item['active']} · HK${item['price']}")
            st.caption(f"{item['step']} · {item['time']} · {'Sensitive-safe' if item['sensitive'] else 'Standard'}")
            am, pm = st.columns(2)
            with am:
                if item["time"] in ("AM", "AM/PM"):
                    add_button(item["name"], "AM", "Add AM", f"cat_am_{item['name']}")
            with pm:
                if item["time"] in ("PM", "AM/PM") and item["step"] != "Broad-Spectrum SPF":
                    add_button(item["name"], "PM", "Add PM", f"cat_pm_{item['name']}")
    st.markdown("### AM / PM Routine Builder")
    morning, evening = st.columns(2)
    for column, routine, title in ((morning, "AM", "Morning (AM) Routine"), (evening, "PM", "Evening (PM) Routine")):
        with column:
            st.markdown(f"#### {title}")
            if not st.session_state[f"{routine.lower()}_routine"]:
                st.info("Add catalogue products to build this routine.")
            for name in st.session_state[f"{routine.lower()}_routine"]:
                render_routine_item(name, routine)
    am_names = st.session_state.am_routine
    pm_names = st.session_state.pm_routine
    cart_names = list(dict.fromkeys(am_names + pm_names))
    subtotal = sum(product(name)["price"] for name in cart_names)
    discount_rate = .15 if len(cart_names) >= 3 else .10 if len(cart_names) >= 2 else 0
    discount = subtotal * discount_rate
    total = subtotal - discount
    st.markdown("### Routine Bundle Checkout Cart")
    st.caption(f"{len(cart_names)} routine items")
    cart_columns = st.columns(3)
    cart_columns[0].metric("Subtotal", f"HK${subtotal:,.2f}")
    cart_columns[1].metric("Discount", f"HK${discount:,.2f}", f"{discount_rate:.0%} off")
    cart_columns[2].metric("Total", f"HK${total:,.2f}")
    if discount_rate == .15:
        st.success("Complete AM/PM Routine Bundle Discount unlocked — 15% off.")
    elif discount_rate == .10:
        st.info("Add one more routine item to unlock the 15% Complete AM/PM Routine Bundle Discount.")
    if st.button("Save Routine to Profile & Checkout", type="primary"):
        save_routine(st.session_state.username, am_names, pm_names, total)
        st.success("Routine saved to your profile. Your bundle is ready for checkout.")


def render_progress() -> None:
    st.markdown("### Skin KPI Progress")
    scans = load_scans(st.session_state.username)
    if not scans:
        st.info("No scans saved for this profile yet.")
        return
    chart_data = {
        "Cleanliness": {row[0]: row[1] for row in scans},
        "Quality": {row[0]: row[2] for row in scans},
        "Hydration": {row[0]: row[3] for row in scans},
        "Pores": {row[0]: row[4] for row in scans},
        "Redness": {row[0]: row[5] for row in scans},
        "Texture": {row[0]: row[6] for row in scans},
    }
    st.line_chart(chart_data)
    st.markdown("### Historical Scan Log")
    st.dataframe(
        [{"Date": row[0], "Cleanliness": row[1], "Quality": row[2], "Hydration": row[3], "Pores": row[4], "Redness": row[5], "Texture": row[6], "Age": row[7]} for row in scans],
        use_container_width=True,
        hide_index=True,
    )
    saved = load_saved_routine(st.session_state.username)
    st.markdown("### Saved Routine")
    if saved:
        am, pm, total = saved
        st.markdown(f"**AM:** {' → '.join(am) or 'Not saved'}")
        st.markdown(f"**PM:** {' → '.join(pm) or 'Not saved'}")
        st.success(f"Saved bundle total: HK${total:,.2f}")
        if st.button("1-Click Reorder Bundle (15% Off)"):
            st.success("Reorder prepared with the 15% bundle discount.")


initialise_database()
st.set_page_config(page_title="Dermalytics | Skin Quality Check", page_icon="✦", layout="wide", initial_sidebar_state="expanded")
st.markdown(
    """<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600&display=swap');
    .stApp{background:#f5f8fa;color:#23343b;font-family:'DM Sans',sans-serif}
    [data-testid="stSidebar"]{background:#102a33}[data-testid="stSidebar"] *{color:#eaf3f3!important}
    [data-testid="stSidebar"] input{background:#f7fbfc!important;color:#173a42!important;-webkit-text-fill-color:#173a42!important}
    [data-testid="stSidebar"] input::placeholder{color:#71878c!important;-webkit-text-fill-color:#71878c!important}
    .brand{color:#8bd1c7;font-size:1.45rem;font-weight:700;letter-spacing:.08em}.brand-note{color:#a9c1c5;font-size:.78rem;margin-bottom:2rem}
    h1{font-family:'Playfair Display',serif;color:#173a42;font-size:2.5rem}.subtitle{color:#6d8186;margin-top:-.8rem;margin-bottom:2rem}
    .panel-title{color:#173a42;font-size:1.18rem;font-weight:700;margin-bottom:1rem}.section-label{color:#719096;font-size:.72rem;font-weight:700;letter-spacing:.14em;margin:.25rem 0 1rem}
    .metric-card,.age-card,.report-card{background:white;border:1px solid #dfeaec;border-radius:14px;padding:1.2rem;box-shadow:0 5px 18px rgba(35,67,75,.05)}
    .metric-card{min-height:120px;border-top:4px solid #61a9bd}.metric-heading{color:#71878c;font-size:.72rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase}
    .score{color:#173a42;font-size:2.35rem;font-weight:700}.out-of{color:#8fa0a4;font-size:.9rem}.age-card{min-height:120px;background:#eef7f5;border-color:#cfe7df}
    .age-value{color:#287c75;font-size:1.5rem;font-weight:700;margin-top:1.05rem}.age-note{color:#7d9996;font-size:.75rem;margin-top:.3rem}
    .report-card{margin-top:1.5rem;padding:1.6rem}.report-title{color:#173a42;font-size:1.2rem;font-weight:700}.report-rule{border-top:1px solid #e6eeee;margin:1rem 0 1.2rem}
    .report-subtitle{color:#719096;font-size:.7rem;font-weight:700;letter-spacing:.12em}.report-card p{color:#52696e;line-height:1.65}
    .side-note{border-top:1px solid #e6eeee;color:#8a9da0;font-size:.75rem;font-style:italic;margin-top:1rem;padding-top:.75rem}
    .guidelines{background:#edf4f4;border-radius:10px;padding:1rem;color:#587176;font-size:.84rem;line-height:1.65}.match-row{background:#fff;border-left:4px solid #75b99f;border-radius:9px;padding:.8rem 1rem;margin:.5rem 0;color:#3b5b60}.match-row small{color:#71878c}.badge{background:#e2f1ed;border-radius:999px;color:#287c75;font-size:.72rem;margin-left:.5rem;padding:.2rem .55rem}
    .routine-item{background:#fff;border:1px solid #dfeaec;border-radius:10px;padding:.8rem;margin:.4rem 0;color:#476167}.routine-item small{color:#719096}.stProgress>div>div{background:#61a9bd}
    </style>""",
    unsafe_allow_html=True,
)

if "result" not in st.session_state:
    st.session_state.result = None
    st.session_state.demo_mode = False
if "am_routine" not in st.session_state:
    st.session_state.am_routine = []
if "pm_routine" not in st.session_state:
    st.session_state.pm_routine = []
with st.sidebar:
    st.markdown('<div class="brand">DERMALYTICS</div><div class="brand-note">Clinical-style skin quality screening</div>', unsafe_allow_html=True)
    st.markdown("### Analysis Settings")
    st.session_state.api_key = st.text_input("API key", type="password", placeholder="Enter your API key")
    st.session_state.model = st.selectbox("Model", MODEL_OPTIONS, index=0)
    username_input = st.text_input("User Profile Login", value="", placeholder="Enter a profile name")
    st.session_state.username = username_input.strip() or "guest_user"
    if st.button("Load Sample Demo Scan (No API Key Needed)", use_container_width=True):
        st.session_state.result = demo_result()
        st.session_state.demo_mode = True
    st.caption("Keys are used only for the current analysis request.")

st.title("Facial Skin Quality Check")
st.markdown('<div class="subtitle">A considered visual review of complexion clarity, texture, and overall appearance.</div>', unsafe_allow_html=True)
tabs = st.tabs(["1 · Diagnosis & Ingredient Matcher", "2 · Routine Builder & E-Shop", "3 · Skin Progress & Saved Routine"])
with tabs[0]:
    render_tab_one()
with tabs[1]:
    render_routine_builder()
with tabs[2]:
    render_progress()
