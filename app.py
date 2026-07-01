import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    RunReportRequest,
    DateRange,
    Metric,
    Dimension,
    OrderBy,
    FilterExpression,
    FilterExpressionList,
    Filter,
    NumericValue,
)
from google.oauth2 import service_account
from datetime import datetime, timedelta
import os
import re

# ── Configuration ──────────────────────────────────────────────────────────────
SITES = {
    "ESG Régions":      "KWDE0RGZCB",
    "Esarc":            "T5EPH0X0FW",
    "Digital Campus":   "8BXHF279VB",
    "Elije":            "BGHLYQB0BS",
    "ESG Sport":        "302430731",
    "ESG Luxe":         "317198069",
    "LISAA":            "302446046",
}

CREDENTIALS_FILE = "service_account.json"

# ── Page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="GA4 Dashboard - Communication",
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


# ── Filter helpers ──────────────────────────────────────────────────────────────
def make_str_filter(field: str, value: str, regexp: bool = False) -> FilterExpression:
    match_type = Filter.StringFilter.MatchType.FULL_REGEXP if regexp else Filter.StringFilter.MatchType.EXACT
    return FilterExpression(filter=Filter(
        field_name=field,
        string_filter=Filter.StringFilter(match_type=match_type, value=value, case_sensitive=False),
    ))

def combine_filters(*exprs) -> FilterExpression | None:
    """AND-combine multiple FilterExpressions, ignoring None values."""
    valid = [e for e in exprs if e is not None]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return FilterExpression(and_group=FilterExpressionList(expressions=valid))

def session_filter(medium: str | None, source: str | None) -> FilterExpression | None:
    """Build a filter for medium and/or source."""
    f_medium = make_str_filter("sessionMedium", medium) if medium else None
    f_source = make_str_filter("sessionSource", source) if source else None
    return combine_filters(f_medium, f_source)


# ── Data fetching ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def fetch_mediums(property_id: str, start_date: str, end_date: str) -> list:
    client = get_client()
    if not client:
        return []
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="sessionMedium")],
        metrics=[Metric(name="totalUsers")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)],
        limit=20,
    )
    response = client.run_report(request)
    return [r.dimension_values[0].value for r in response.rows if r.dimension_values[0].value not in ("", "(not set)")]


@st.cache_data(ttl=3600)
def fetch_sources(property_id: str, start_date: str, end_date: str, medium: str) -> list:
    client = get_client()
    if not client:
        return []
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="sessionSource")],
        metrics=[Metric(name="totalUsers")],
        dimension_filter=make_str_filter("sessionMedium", medium),
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)],
        limit=30,
    )
    response = client.run_report(request)
    return [r.dimension_values[0].value for r in response.rows if r.dimension_values[0].value not in ("", "(not set)")]


@st.cache_data(ttl=3600)
def fetch_kpis(property_id: str, start_date: str, end_date: str, medium: str = None, source: str = None):
    client = get_client()
    if not client:
        return None

    sf = session_filter(medium, source)

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        metrics=[Metric(name="totalUsers"), Metric(name="keyEvents")],
        **({"dimension_filter": sf} if sf else {}),
    )
    response = client.run_report(request)
    row = response.rows[0] if response.rows else None
    if not row:
        return {"total_users": 0, "key_events": 0, "key_event_rate": 0.0}

    total_users = int(row.metric_values[0].value)
    key_events  = int(row.metric_values[1].value)

    request_converters = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="isKeyEvent")],
        metrics=[Metric(name="totalUsers")],
        **({"dimension_filter": sf} if sf else {}),
    )
    response_conv = client.run_report(request_converters)
    converting_users = 0
    for row in response_conv.rows:
        if row.dimension_values[0].value == "true":
            converting_users = int(row.metric_values[0].value)
            break
    key_event_rate = round((converting_users / total_users * 100), 2) if total_users > 0 else 0.0

    return {"total_users": total_users, "key_events": key_events, "key_event_rate": key_event_rate}


@st.cache_data(ttl=3600)
def fetch_pages(property_id: str, start_date: str, end_date: str, medium: str = None, source: str = None):
    client = get_client()
    if not client:
        return pd.DataFrame()

    sf = session_filter(medium, source)

    req_all = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPage")],
        metrics=[Metric(name="totalUsers"), Metric(name="keyEvents")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)],
        limit=50,
        **({"dimension_filter": sf} if sf else {}),
    )
    resp_all = client.run_report(req_all)

    req_ke = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPage"), Dimension(name="isKeyEvent")],
        metrics=[Metric(name="totalUsers")],
        **({"dimension_filter": sf} if sf else {}),
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
            "Landing Page": path,
            "Total Users":  total_users,
            "Key Events":   key_events,
            "Taux":         rate,
        })

    df = pd.DataFrame(rows)
    df = df[df["Key Events"] >= 1].reset_index(drop=True)
    return df


@st.cache_data(ttl=3600)
def fetch_page_paths(property_id: str, start_date: str, end_date: str, medium: str = None, source: str = None):
    client = get_client()
    if not client:
        return pd.DataFrame()

    sf = session_filter(medium, source)

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="pagePath")],
        metrics=[Metric(name="totalUsers"), Metric(name="screenPageViews")],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="totalUsers"), desc=True)],
        limit=50,
        **({"dimension_filter": sf} if sf else {}),
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        rows.append({
            "Chemin de page":  row.dimension_values[0].value,
            "Total Users":     int(row.metric_values[0].value),
            "Pages vues":      int(row.metric_values[1].value),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def fetch_url_kpis(property_id: str, start_date: str, end_date: str, url_filter: str):
    client = get_client()
    if not client:
        return None

    lp_filter = FilterExpression(
        filter=Filter(
            field_name="landingPage",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                value=re.escape(url_filter) + r"(\?.*)?",
                case_sensitive=False,
            ),
        )
    )

    # Requête 1 : totalUsers + keyEvents par landingPage contenant url_filter
    req1 = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPage")],
        metrics=[Metric(name="totalUsers"), Metric(name="keyEvents")],
        dimension_filter=lp_filter,
    )
    resp1 = client.run_report(req1)

    total_users = sum(int(r.metric_values[0].value) for r in resp1.rows)
    key_events  = sum(int(r.metric_values[1].value) for r in resp1.rows)

    if total_users == 0:
        return {"total_users": 0, "key_events": 0, "key_event_rate": 0.0}

    # Requête 2 : users convertisseurs via isKeyEvent dimension (même approche que tableau pages)
    req2 = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPage"), Dimension(name="isKeyEvent")],
        metrics=[Metric(name="totalUsers")],
        dimension_filter=lp_filter,
    )
    resp2 = client.run_report(req2)

    converting_users = 0
    for r in resp2.rows:
        if r.dimension_values[1].value == "true":
            converting_users += int(r.metric_values[0].value)

    key_event_rate = round((converting_users / total_users * 100), 2) if total_users > 0 else 0.0

    return {"total_users": total_users, "key_events": key_events, "key_event_rate": key_event_rate}


@st.cache_data(ttl=3600)
def fetch_page_path_kpis(property_id: str, start_date: str, end_date: str, url_filter: str):
    client = get_client()
    if not client:
        return None

    path_filter = FilterExpression(
        filter=Filter(
            field_name="pagePath",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                value=re.escape(url_filter) + r"(\?.*)?",
                case_sensitive=False,
            ),
        )
    )

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        metrics=[Metric(name="totalUsers"), Metric(name="screenPageViews")],
        dimension_filter=path_filter,
    )
    response = client.run_report(request)
    row = response.rows[0] if response.rows else None
    if not row:
        return {"total_users": 0, "page_views": 0}

    return {
        "total_users": int(row.metric_values[0].value),
        "page_views":  int(row.metric_values[1].value),
    }


@st.cache_data(ttl=3600)
def fetch_page_path_traffic(property_id: str, start_date: str, end_date: str, granularity: str, url_filter: str):
    client = get_client()
    if not client:
        return pd.DataFrame()

    dim_map = {"Jour": "date", "Semaine": "isoWeek", "Mois": "yearMonth"}
    dimension = dim_map[granularity]

    path_filter = FilterExpression(
        filter=Filter(
            field_name="pagePath",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                value=re.escape(url_filter) + r"(\?.*)?",
                case_sensitive=False,
            ),
        )
    )

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=dimension)],
        metrics=[Metric(name="totalUsers")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dimension))],
        dimension_filter=path_filter,
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        rows.append({"period": row.dimension_values[0].value, "users": int(row.metric_values[0].value)})

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if granularity == "Jour":
        df["period"] = pd.to_datetime(df["period"], format="%Y%m%d")
    elif granularity == "Semaine":
        df["period_display"] = df["period"].apply(lambda x: f"S{x[4:]} {x[:4]}" if len(x) >= 6 else x)
    elif granularity == "Mois":
        df["period_display"] = df["period"].apply(lambda x: datetime.strptime(x, "%Y%m").strftime("%b %Y") if len(x) == 6 else x)

    return df


@st.cache_data(ttl=3600)
def fetch_url_traffic(property_id: str, start_date: str, end_date: str, granularity: str, url_filter: str):
    client = get_client()
    if not client:
        return pd.DataFrame()

    dim_map = {"Jour": "date", "Semaine": "isoWeek", "Mois": "yearMonth"}
    dimension = dim_map[granularity]

    filter_expr = FilterExpression(
        filter=Filter(
            field_name="landingPage",
            string_filter=Filter.StringFilter(
                match_type=Filter.StringFilter.MatchType.FULL_REGEXP,
                value=re.escape(url_filter) + r"(\?.*)?",
                case_sensitive=False,
            ),
        )
    )

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=dimension)],
        metrics=[Metric(name="totalUsers"), Metric(name="keyEvents")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dimension))],
        dimension_filter=filter_expr,
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        rows.append({
            "period":     row.dimension_values[0].value,
            "users":      int(row.metric_values[0].value),
            "key_events": int(row.metric_values[1].value),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    if granularity == "Jour":
        df["period"] = pd.to_datetime(df["period"], format="%Y%m%d")
    elif granularity == "Semaine":
        df["period_display"] = df["period"].apply(lambda x: f"S{x[4:]} {x[:4]}" if len(x) >= 6 else x)
    elif granularity == "Mois":
        df["period_display"] = df["period"].apply(lambda x: datetime.strptime(x, "%Y%m").strftime("%b %Y") if len(x) == 6 else x)

    return df


@st.cache_data(ttl=3600)
def fetch_traffic(property_id: str, start_date: str, end_date: str, granularity: str, medium: str = None, source: str = None):
    client = get_client()
    if not client:
        return pd.DataFrame()

    dim_map = {"Jour": "date", "Semaine": "isoWeek", "Mois": "yearMonth"}
    dimension = dim_map[granularity]
    sf = session_filter(medium, source)

    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name=dimension)],
        metrics=[Metric(name="totalUsers"), Metric(name="keyEvents")],
        order_bys=[OrderBy(dimension=OrderBy.DimensionOrderBy(dimension_name=dimension))],
        **({"dimension_filter": sf} if sf else {}),
    )
    response = client.run_report(request)

    rows = []
    for row in response.rows:
        rows.append({
            "period":     row.dimension_values[0].value,
            "users":      int(row.metric_values[0].value),
            "key_events": int(row.metric_values[1].value),
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


@st.cache_data(ttl=3600)
def fetch_search_queries(property_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    client = get_client()
    if not client:
        return pd.DataFrame()
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="searchTerm")],
        metrics=[
            Metric(name="organicGoogleSearchClicks"),
            Metric(name="organicGoogleSearchImpressions"),
            Metric(name="organicGoogleSearchClickThroughRate"),
            Metric(name="organicGoogleSearchAveragePosition"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="organicGoogleSearchClicks"), desc=True)],
        limit=100,
    )
    try:
        response = client.run_report(request)
    except Exception as e:
        return pd.DataFrame({"_error": [str(e)]})
    rows = []
    for row in response.rows:
        rows.append({
            "Requête":     row.dimension_values[0].value,
            "Clics":       int(row.metric_values[0].value),
            "Impressions": int(row.metric_values[1].value),
            "CTR":         round(float(row.metric_values[2].value) * 100, 2),
            "Position":    round(float(row.metric_values[3].value), 1),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600)
def fetch_search_pages(property_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    client = get_client()
    if not client:
        return pd.DataFrame()
    request = RunReportRequest(
        property=f"properties/{property_id}",
        date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
        dimensions=[Dimension(name="landingPagePlusQueryString")],
        metrics=[
            Metric(name="organicGoogleSearchClicks"),
            Metric(name="organicGoogleSearchImpressions"),
            Metric(name="organicGoogleSearchClickThroughRate"),
            Metric(name="organicGoogleSearchAveragePosition"),
        ],
        order_bys=[OrderBy(metric=OrderBy.MetricOrderBy(metric_name="organicGoogleSearchClicks"), desc=True)],
        limit=100,
    )
    try:
        response = client.run_report(request)
    except Exception:
        return pd.DataFrame()
    rows = []
    for row in response.rows:
        rows.append({
            "Page de destination": row.dimension_values[0].value,
            "Clics":               int(row.metric_values[0].value),
            "Impressions":         int(row.metric_values[1].value),
            "CTR":                 round(float(row.metric_values[2].value) * 100, 2),
            "Position":            round(float(row.metric_values[3].value), 1),
        })
    return pd.DataFrame(rows)


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
    "ESG Sport":      "302430731",
    "ESG Luxe":       "317198069",
    "LISAA":          "302446046",
}

LOGOS = {
    "ESG Régions":    {"type": "local", "src": "logo_esg.png", "bg": "transparent", "fallback": "https://www.esg.fr/sites/all/themes/bootstrapv4_studialis/img/svg/logo_blanc_50_ans.svg", "fallback_bg": "#1a1a2e"},
    "Esarc":          {"type": "url",   "src": "https://www.esarc-evolution.fr/sites/default/files/ggeedu_vars/logo_esarc_quadri.svg", "bg": "transparent"},
    "Digital Campus": {"type": "url",   "src": "https://www.digital-campus.fr/sites/all/themes/digital_campus/img/logos/logo-digital-campus-dark.svg", "bg": "transparent"},
    "Elije":          {"type": "url",   "src": "https://www.elije.fr/sites/default/files/ggeedu_vars/logo-elije-noir.svg", "bg": "transparent"},
    "ESG Sport":      {"type": "url",   "src": "https://www.esg-sport.com/sites/default/files/images/2025-04/logo-sport.png", "bg": "transparent"},
    "ESG Luxe":       {"type": "url",   "src": "https://www.esg-luxe.com/sites/all/themes/bootstrapv4_studialis/img/svg/logo_luxe.svg", "bg": "transparent"},
    "LISAA":          {"type": "url",   "src": "https://www.lisaa.com/sites/all/themes/lisaa/img/svg/logo-rouge.svg", "bg": "transparent"},
}


# ── UI ──────────────────────────────────────────────────────────────────────────
def main():
    # Header
    st.markdown("## GA4 Dashboard - Communication")
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
    # (sidebar filters for medium/source added below after property_id is known)
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

    # ── Sidebar : filtres Source / Support ──────────────────────────────────────
    with st.sidebar:
        st.markdown("---")
        st.markdown("**🔎 Filtres trafic**")

        mediums = fetch_mediums(property_id, start_str, end_str)
        medium_options = ["Tous"] + mediums
        selected_medium_label = st.selectbox("Support (medium)", medium_options)
        selected_medium = None if selected_medium_label == "Tous" else selected_medium_label

        if selected_medium:
            sources = fetch_sources(property_id, start_str, end_str, selected_medium)
            source_options = ["Toutes"] + sources
            selected_source_label = st.selectbox("Source", source_options)
            selected_source = None if selected_source_label == "Toutes" else selected_source_label
        else:
            selected_source = None

    # ── Onglets ─────────────────────────────────────────────────────────────────
    tab_general, tab_sc = st.tabs(["📊 Vue générale", "🔍 Search Console"])

    with tab_sc:
        render_search_console(property_id, start_str, end_str)

    with tab_general:
        # ── Site title avec logo ──────────────────────────────────────────────
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
            kpis = fetch_kpis(property_id, start_str, end_str, selected_medium, selected_source)

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
            df = fetch_traffic(property_id, start_str, end_str, granularity, selected_medium, selected_source)

        if not df.empty:
            if granularity == "Jour":
                x_col = "period"
                x_label = "Date"
            else:
                x_col = "period_display"
                x_label = "Période"

            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(
                x=df[x_col], y=df["users"],
                name="Utilisateurs",
                mode="lines",
                line=dict(color="#4f8ef7", width=2),
                fill="tozeroy",
                fillcolor="rgba(79,142,247,0.12)",
            ), secondary_y=False)
            fig.add_trace(go.Scatter(
                x=df[x_col], y=df["key_events"],
                name="Key Events",
                mode="lines",
                line=dict(color="#e05c2a", width=2),
                fill="tozeroy",
                fillcolor="rgba(224,92,42,0.08)",
            ), secondary_y=True)
            fig.update_layout(
                title=f"Utilisateurs & Key Events par {granularity.lower()} — {site_name}",
                plot_bgcolor="white",
                paper_bgcolor="white",
                hovermode="x unified",
                margin=dict(t=50, b=20, l=20, r=60),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            )
            fig.update_xaxes(showgrid=False)
            fig.update_yaxes(title_text="Utilisateurs", gridcolor="#f0f0f0", title_font=dict(color="#4f8ef7"), tickfont=dict(color="#4f8ef7"), secondary_y=False)
            fig.update_yaxes(title_text="Key Events", showgrid=False, title_font=dict(color="#e05c2a"), tickfont=dict(color="#e05c2a"), secondary_y=True)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Aucune donnée de trafic disponible pour cette période.")

        # ── Pages table ─────────────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 📄 Utilisateurs par Landing page")
        st.caption("Top 50 pages (page d'entrée) triées par utilisateurs — 30 derniers jours")

        with st.spinner("Chargement des pages…"):
            df_pages = fetch_pages(property_id, start_str, end_str, selected_medium, selected_source)

        if not df_pages.empty:
            df_display = df_pages.copy()
            df_display["Total Users"]  = df_display["Total Users"].apply(lambda x: f"{x:,}")
            df_display["Key Events"]   = df_display["Key Events"].apply(lambda x: f"{x:,}")
            df_display["Taux"]         = df_display["Taux"].apply(lambda x: f"{x:.2f}%")
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune donnée de page disponible pour cette période.")

        # ── Page paths table ─────────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🗂️ Utilisateurs par chemin de page")
        st.caption("Top 50 pages (page d'entrée + navigation) triées par utilisateurs — 30 derniers jours")

        with st.spinner("Chargement des chemins de page…"):
            df_paths = fetch_page_paths(property_id, start_str, end_str, selected_medium, selected_source)

        if not df_paths.empty:
            df_paths_display = df_paths.copy()
            df_paths_display["Total Users"] = df_paths_display["Total Users"].apply(lambda x: f"{x:,}")
            df_paths_display["Pages vues"]  = df_paths_display["Pages vues"].apply(lambda x: f"{x:,}")
            st.dataframe(df_paths_display, use_container_width=True, hide_index=True)
        else:
            st.info("Aucune donnée disponible pour cette période.")

        # ── Recherche par page ──────────────────────────────────────────────────────
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🔍 Analyse d'une page")
        url_search = st.text_input(
            "Saisir une URL complète ou un chemin",
            placeholder="ex: https://www.esg.fr/formations/bachelor  ou  /formations/bachelor",
        )

        if url_search:
            import urllib.parse
            parsed = urllib.parse.urlparse(url_search.strip())
            url_search = parsed.path if parsed.scheme else url_search.strip()
            if not url_search:
                url_search = "/"

            st.caption(f"Résultats pour la page : **{url_search}**")
            x_col = "period" if granularity == "Jour" else "period_display"

            col_lp, col_pp = st.columns(2)

            # ── Colonne Landing Page ─────────────────────────────────────────────
            with col_lp:
                st.markdown("#### 📥 Landing page")
                st.caption("Utilisateurs entrés par cette page")
                with st.spinner("Chargement…"):
                    lp_kpis = fetch_url_kpis(property_id, start_str, end_str, url_search)

                if lp_kpis and lp_kpis["total_users"] > 0:
                    st.markdown(f"""
                    <div class="kpi-card" style="margin-bottom:8px">
                        <div class="kpi-label">Total Users</div>
                        <div class="kpi-value">{format_number(lp_kpis['total_users'])}</div>
                        <div class="kpi-sub">entrées sur la période</div>
                    </div>""", unsafe_allow_html=True)
                    st.markdown(f"""
                    <div class="kpi-card" style="margin-bottom:8px">
                        <div class="kpi-label">Key Events</div>
                        <div class="kpi-value">{format_number(lp_kpis['key_events'])}</div>
                        <div class="kpi-sub">événements clés déclenchés</div>
                    </div>""", unsafe_allow_html=True)
                    st.markdown(f"""
                    <div class="kpi-card" style="margin-bottom:12px">
                        <div class="kpi-label">Key Event Rate</div>
                        <div class="kpi-value">{lp_kpis['key_event_rate']}%</div>
                        <div class="kpi-sub">utilisateurs avec ≥1 key event</div>
                    </div>""", unsafe_allow_html=True)

                    with st.spinner("Chargement du graphique…"):
                        df_lp = fetch_url_traffic(property_id, start_str, end_str, granularity, url_search)
                    if not df_lp.empty:
                        fig_lp = go.Figure()
                        fig_lp.add_trace(go.Scatter(
                            x=df_lp[x_col], y=df_lp["users"],
                            name="Utilisateurs", mode="lines",
                            line=dict(color="#f7864f", width=2),
                            fill="tozeroy", fillcolor="rgba(247,134,79,0.15)",
                        ))
                        fig_lp.add_trace(go.Scatter(
                            x=df_lp[x_col], y=df_lp["key_events"],
                            name="Key Events", mode="lines",
                            line=dict(color="#9b59b6", width=2),
                            fill="tozeroy", fillcolor="rgba(155,89,182,0.10)",
                        ))
                        fig_lp.update_layout(
                            title=f"Utilisateurs & Key Events — {url_search}",
                            plot_bgcolor="white", paper_bgcolor="white",
                            xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#f0f0f0"),
                            hovermode="x unified", margin=dict(t=50, b=20, l=20, r=20),
                            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                        )
                        st.plotly_chart(fig_lp, use_container_width=True)
                else:
                    st.info("Aucune donnée landing page trouvée.")

            # ── Colonne Chemin de page ───────────────────────────────────────────
            with col_pp:
                st.markdown("#### 🗂️ Chemin de page")
                st.caption("Utilisateurs ayant visité cette page (entrée + navigation)")
                with st.spinner("Chargement…"):
                    pp_kpis = fetch_page_path_kpis(property_id, start_str, end_str, url_search)

                if pp_kpis and pp_kpis["total_users"] > 0:
                    st.markdown(f"""
                    <div class="kpi-card" style="margin-bottom:8px">
                        <div class="kpi-label">Total Users</div>
                        <div class="kpi-value">{format_number(pp_kpis['total_users'])}</div>
                        <div class="kpi-sub">utilisateurs ayant vu la page</div>
                    </div>""", unsafe_allow_html=True)
                    st.markdown(f"""
                    <div class="kpi-card" style="margin-bottom:8px">
                        <div class="kpi-label">Pages vues</div>
                        <div class="kpi-value">{format_number(pp_kpis['page_views'])}</div>
                        <div class="kpi-sub">vues totales (avec revisites)</div>
                    </div>""", unsafe_allow_html=True)

                    with st.spinner("Chargement du graphique…"):
                        df_pp = fetch_page_path_traffic(property_id, start_str, end_str, granularity, url_search)
                    if not df_pp.empty:
                        fig_pp = px.area(df_pp, x=x_col, y="users",
                            labels={"users": "Utilisateurs", x_col: ""},
                            title=f"Trafic chemin de page — {url_search}",
                            color_discrete_sequence=["#4fc49e"])
                        fig_pp.update_traces(fill="tozeroy", line=dict(width=2), fillcolor="rgba(79,196,158,0.15)")
                        fig_pp.update_layout(plot_bgcolor="white", paper_bgcolor="white",
                            xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#f0f0f0"),
                            hovermode="x unified", margin=dict(t=50, b=20, l=20, r=20))
                        st.plotly_chart(fig_pp, use_container_width=True)
                else:
                    st.info("Aucune donnée chemin de page trouvée.")


def render_search_console(property_id, start_str, end_str):
    st.markdown("### 🔍 Search Console — Requêtes")
    st.caption("Top 100 requêtes de recherche naturelle Google, triées par clics")

    with st.spinner("Chargement des requêtes…"):
        df_q = fetch_search_queries(property_id, start_str, end_str)

    if not df_q.empty and "_error" in df_q.columns:
        st.error(f"Erreur API : {df_q['_error'].iloc[0]}")
    elif not df_q.empty:
        df_q_display = df_q.copy()
        df_q_display["Clics"]       = df_q_display["Clics"].apply(lambda x: f"{x:,}")
        df_q_display["Impressions"] = df_q_display["Impressions"].apply(lambda x: f"{x:,}")
        df_q_display["CTR"]         = df_q_display["CTR"].apply(lambda x: f"{x:.2f}%")
        df_q_display["Position"]    = df_q_display["Position"].apply(lambda x: f"{x:.1f}")
        st.dataframe(df_q_display, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune donnée Search Console disponible. Vérifie que Search Console est lié à cette propriété GA4.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🗂️ Search Console — Pages de destination")
    st.caption("Top 100 pages de destination + chaîne de requête, triées par clics")

    with st.spinner("Chargement des pages…"):
        df_p = fetch_search_pages(property_id, start_str, end_str)

    if not df_p.empty:
        df_p_display = df_p.copy()
        df_p_display["Clics"]       = df_p_display["Clics"].apply(lambda x: f"{x:,}")
        df_p_display["Impressions"] = df_p_display["Impressions"].apply(lambda x: f"{x:,}")
        df_p_display["CTR"]         = df_p_display["CTR"].apply(lambda x: f"{x:.2f}%")
        df_p_display["Position"]    = df_p_display["Position"].apply(lambda x: f"{x:.1f}")
        st.dataframe(df_p_display, use_container_width=True, hide_index=True)
    else:
        st.info("Aucune donnée Search Console disponible.")


if __name__ == "__main__":
    main()
