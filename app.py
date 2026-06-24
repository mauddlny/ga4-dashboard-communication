import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Metric,
    Dimension,
    OrderBy,
    FilterExpression,
    Filter,
    NumericValue,
)
from google.oauth2 import service_account
from datetime import datetime, timedelta
import os

# ── Configuration ──────────────────────────────────────────────────────────────
SITES = {
    "ESG Régions":      "KWDE0RGZCB",
    "Esarc":            "T5EPH0X0FW",
    "Digital Campus":   "8BXHF279VB",
    "Elije":            "BGHLYQB0BS",
}

CREDENTIALS_FILE = "service_account.json"

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GA4 Dashboard",
    page_icon="📊",
    layout="wide",
)

# ── Custom CSS ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .kpi-card {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 20px 24px;
        text-align: center;
        border: 1px solid #e0e0e0;
    }
    .kpi-label {
        font-size: 13px;
        color: #666;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 8px;
    }
    .kpi-value {
        font-size: 36px;
        font-weight: 700;
        color: #1a1a2e;
    }
    .kpi-sub {
        font-size: 12px;
        color: #999;
        margin-top: 4px;
    }
    div[data-testid="stMetricValue"] { font-size: 2rem; }
</style>
""", unsafe_allow_html=True)


# ── Auth ────────────────────────────────────────────────────────────────────────
@st.cache_resource
def get_client():
    try:
        # Streamlit Cloud : credentials dans st.secrets
        if "gcp_service_account" in st.secrets:
            import json
            creds = service_account.Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]),
                scopes=["https://www.googleapis.com/auth/analytics.readonly"],
            )
            return BetaAnalyticsDataClient(credentials=creds)
    except Exception:
        pass

    # Local : fichier service_account.json
    if os.path.exists(CREDENTIALS_FILE):
        creds = service_account.Credentials.from_service_account_file(
            CREDENTIALS_FILE,
            scopes=["https://www.googleapis.com/auth/analytics.readonly"],
        )
        return BetaAnalyticsDataClient(credentials=creds)

    return None


# ── Data fetching ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_kpis(property_id: str, start_date: str, end_date: str):
    client = get_client()
    if not client:
        return None

    # Total users + key events
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        metrics=[
            Metric(name="totalUsers"),
            Metric(name="keyEvents"),
        ],
    )
    response = client.run_report(request)
    row = response.rows[0] if response.rows else None
    if not row:
        return {"total_users": 0, "key_events": 0, "key_event_rate": 0.0}

    total_users = int(row.metric_values[0].value)
    key_events  = int(row.metric_values[1].value)

    # Users who triggered at least 1 key event via isKeyEvent dimension
    request_converters = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="isKeyEvent")],
        metrics=[Metric(name="totalUsers")],
    )
    response_conv = client.run_report(request_converters)
    converting_users = 0
    for row in response_conv.rows:
        if row.dimension_values[0].value == "true":
            converting_users = int(row.metric_values[0].value)
            break
    key_event_rate = round((converting_users / total_users * 100), 2) if total_users > 0 else 0.0

    return {
        "total_users":    total_users,
        "key_events":     key_events,
        "key_event_rate": key_event_rate,
    }


@st.cache_data(ttl=3600)
def fetch_pages(property_id: str, start_date: str, end_date: str):
    client = get_client()
    if not client:
        return pd.DataFrame()

    # Requête 1 : Total Users + Key Events par landing page
    req_all = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPage")],
        metrics=[
            Metric(name="totalUsers"),
            Metric(name="keyEvents"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)],
        limit=50,
    )
    resp_all = client.run_report(req_all)

    # Requête 2 : Users avec isKeyEvent = true par landing page
    req_ke = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[
            Dimension(name="landingPage"),
            Dimension(name="isKeyEvent"),
        ],
        metrics=[Metric(name="totalUsers")],
    )
    resp_ke = client.run_report(req_ke)

    # Dict {landingPage: converting_users}
    ke_users_by_path = {}
    for row in resp_ke.rows:
        path  = row.dimension_values[0].value
        is_ke = row.dimension_values[1].value
        users = int(row.metric_values[0].value)
        if is_ke == "true":
            ke_users_by_path[path] = users

    rows = []
    for row in resp_all.rows:
        path        = row.dimension_values[0].value
        total_users = int(row.metric_values[0].value)
        key_events  = int(row.metric_values[1].value)
        conv_users  = ke_users_by_path.get(path, 0)
        rate        = round(conv_users / total_users * 100, 2) if total_users > 0 else 0.0
        rows.append({
            "URL":         path,
            "Total Users": total_users,
            "Key Events":  key_events,
            "Taux":        rate,
        })

    df = pd.DataFrame(rows)
    df = df[df["Key Events"] >= 1].reset_index(drop=True)
    return df


@st.cache_data(ttl=3600)
def fetch_traffic(property_id: str, start_date: str, end_date: str, granularity: str):
    client = get_client()
    if not client:
        return pd.DataFrame()

    dim_map = {"Jour": "date", "Semaine": "isoWeek", "Mois": "yearMonth"}
    dimension = dim_map[granularity]

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=dimension)],
        metrics=[Metric(name="totalUsers")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dimension))],
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        rows.append({
            "period": row.dimension_values[0].value,
            "users":  int(row.metric_values[0].value),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Format period label
    if granularity == "Jour":
        df["period"] = pd.to_datetime(df["period"], format="%Y%m%d")
    elif granularity == "Semaine":
        # isoWeek format: YYYYWW
        df["period_label"] = df["period"].apply(
            lambda x: f"S{x[4:]} {x[:4]}" if len(x) >= 6 else x
        )
        df = df.rename(columns={"period_label": "period_display"})
    elif granularity == "Mois":
        df["period_display"] = df["period"].apply(
            lambda x: datetime.strptime(x, "%Y%m").strftime("%b %Y") if len(x) == 6 else x
        )

    return df


# ── Helpers ─────────────────────────────────────────────────────────────────────
def format_number(n):
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}k"
    return str(n)

def property_id_from_measurement_id(mid: str) -> str:
    """
    The property ID in GA4 API is numeric.
    Since we store measurement IDs (G-XXXXX), the user must map them.
    This dict holds the numeric property IDs.
    """
    return PROPERTY_IDS.get(mid, mid)


# ── IMPORTANT: replace these with your real numeric Property IDs ─────────────
# Go to GA4 > Admin > Property Settings to find the numeric ID (e.g. 123456789)
PROPERTY_IDS = {
    "ESG Régions":    "302479484",
    "Esarc":          "302461432",
    "Digital Campus": "302438676",
    "Elije":          "314845877",
}

LOGOS = {
    "ESG Régions":    {"type": "local", "src": "logo_esg.png", "bg": "transparent", "fallback": "https://www.esg.fr/sites/all/themes/bootstrapv4_studialis/img/svg/logo_blanc_50_ans.svg", "fallback_bg": "#1a1a2e"},
    "Esarc":          {"type": "url",   "src": "https://www.esarc-evolution.fr/sites/default/files/ggeedu_vars/logo_esarc_quadri.svg", "bg": "transparent"},
    "Digital Campus": {"type": "url",   "src": "https://www.digital-campus.fr/sites/all/themes/digital_campus/img/logos/logo-digital-campus-dark.svg", "bg": "transparent"},
    "Elije":          {"type": "url",   "src": "https://www.elije.fr/sites/default/files/ggeedu_vars/logo-elije-noir.svg", "bg": "transparent"},
}


# ── UI ──────────────────────────────────────────────────────────────────────────
def main():
    # Header
    st.markdown("## GA4 Dashboard")
    st.divider()

    # ── Sidebar controls ────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("### ⚙️ Paramètres")

        site_name = st.selectbox(
            "Site",
            options=list(SITES.keys()),
        )

        st.markdown("---")

        today     = datetime.today().date()
        yesterday = today - timedelta(days=1)
        default_start = yesterday - timedelta(days=29)

        date_range = st.date_input(
            "📅 Période",
            value=(default_start, yesterday),
            max_value=yesterday,
        )

        st.markdown("---")

        granularity = st.radio(
            "📈 Granularité du graphique",
            options=["Jour", "Semaine", "Mois"],
            horizontal=True,
        )

    # ── Validate date range ─────────────────────────────────────────────────────
    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_date, end_date = date_range
    else:
        st.warning("Sélectionne une plage de dates complète.")
        return

    start_str = start_date.strftime("%Y-%m-%d")
    end_str   = end_date.strftime("%Y-%m-%d")
    property_id = PROPERTY_IDS.get(site_name)

    # ── Check credentials ───────────────────────────────────────────────────────
    client = get_client()
    if not client:
        st.error(
            "⚠️ Credentials introuvables. "
            "Place `service_account.json` dans le dossier du projet ou configure les Secrets Streamlit."
        )
        st.info("👉 Consulte le README pour créer ton compte de service Google.")
        return

    if "REPLACE_" in str(property_id):
        st.warning(
            f"⚠️ Remplace `REPLACE_{site_name.upper().replace(' ', '_')}_PROPERTY_ID` "
            f"par l'ID numérique de ta propriété GA4 dans `app.py`."
        )
        return

    # ── Site title avec logo ────────────────────────────────────────────────────
    logo_cfg = LOGOS.get(site_name, {})
    if logo_cfg:
        if logo_cfg["type"] == "local" and os.path.exists(logo_cfg["src"]):
            import base64
            with open(logo_cfg["src"], "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            img_src = f"data:image/png;base64,{b64}"
            bg = logo_cfg["bg"]
        elif logo_cfg["type"] == "local" and "fallback" in logo_cfg:
            img_src = logo_cfg["fallback"]
            bg = logo_cfg.get("fallback_bg", "transparent")
        else:
            img_src = logo_cfg["src"]
            bg = logo_cfg["bg"]
        st.markdown(
            f"""<div style="background:{bg}; display:inline-block; padding:6px 12px; border-radius:8px; margin-bottom:8px;">
                <img src="{img_src}" style="height:52px; width:auto; display:block;" />
            </div>""",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(f"### {site_name}")
    st.caption(f"Période : {start_date.strftime('%d/%m/%Y')} → {end_date.strftime('%d/%m/%Y')}")

    # ── KPIs ────────────────────────────────────────────────────────────────────
    with st.spinner("Chargement des KPIs…"):
        kpis = fetch_kpis(property_id, start_str, end_str)

    if kpis:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Total Users</div>
                <div class="kpi-value">{format_number(kpis['total_users'])}</div>
                <div class="kpi-sub">sur la période sélectionnée</div>
            </div>""", unsafe_allow_html=True)
        with col2:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Key Events</div>
                <div class="kpi-value">{format_number(kpis['key_events'])}</div>
                <div class="kpi-sub">événements clés déclenchés</div>
            </div>""", unsafe_allow_html=True)
        with col3:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">Key Event Rate</div>
                <div class="kpi-value">{kpis['key_event_rate']}%</div>
                <div class="kpi-sub">utilisateurs avec ≥1 key event</div>
            </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Traffic chart ────────────────────────────────────────────────────────────
    with st.spinner("Chargement du graphique…"):
        df = fetch_traffic(property_id, start_str, end_str, granularity)

    if not df.empty:
        if granularity == "Jour":
            x_col = "period"
            x_label = "Date"
        else:
            x_col = "period_display"
            x_label = "Période"

        fig = px.area(
            df,
            x=x_col,
            y="users",
            labels={"users": "Utilisateurs", x_col: x_label},
            title=f"Trafic par {granularity.lower()} — {site_name}",
            color_discrete_sequence=["#4f8ef7"],
        )
        fig.update_traces(
            fill="tozeroy",
            line=dict(width=2),
            fillcolor="rgba(79, 142, 247, 0.15)",
        )
        fig.update_layout(
            plot_bgcolor="white",
            paper_bgcolor="white",
            xaxis=dict(showgrid=False),
            yaxis=dict(gridcolor="#f0f0f0"),
            hovermode="x unified",
            margin=dict(t=50, b=20, l=20, r=20),
        )
        st.plotly_chart(fig, width="stretch")
    else:
        st.info("Aucune donnée de trafic disponible pour cette période.")

    # ── Pages table ─────────────────────────────────────────────────────────────
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📄 Détail par page")
    st.caption("Top 50 pages triées par utilisateurs — 30 derniers jours")

    with st.spinner("Chargement des pages…"):
        df_pages = fetch_pages(property_id, start_str, end_str)

    if not df_pages.empty:
        df_display = df_pages.copy()
        df_display["Total Users"] = df_display["Total Users"].apply(lambda x: f"{x:,}")
        df_display["Key Events"]  = df_display["Key Events"].apply(lambda x: f"{x:,}")
        df_display["Taux"]        = df_display["Taux"].apply(lambda x: f"{x:.2f}%")
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune donnée de page disponible pour cette période.")


if __name__ == "__main__":
    main()
