# main.py

import io
import gzip
import requests
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# =========================================================
# 1. 기본 설정
# =========================================================

st.set_page_config(
    page_title="전세계 고령화 지도",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 전세계 고령화 지도")

st.caption(
    "65세 이상 인구가 전체 인구에서 차지하는 비율을 "
    "국가별로 비교합니다."
)


# =========================================================
# 2. 데이터 주소
# =========================================================

# 한국 읍·면·동 인구 데이터
KOREA_POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/population_yearly.csv.gz"
)

# 한국 시군구 경계 데이터
KOREA_GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/"
    "main/data/boundaries/sigungu_kr.geojson"
)

# World Bank
# Population ages 65 and above (% of total population)
WORLD_BANK_URL = (
    "https://api.worldbank.org/v2/country/all/"
    "indicator/SP.POP.65UP.TO.ZS"
    "?format=json&per_page=20000"
)


# =========================================================
# 3. 전세계 인구 데이터 불러오기
# =========================================================

@st.cache_data
def load_world_data():
    """
    World Bank에서 국가별 65세 이상 인구 비율을 가져온다.

    기존 코드에서는 국가 이름을 가져오기 위해
    World Bank 국가 API를 한 번 더 호출했는데,
    그 과정에서 iso3Code 열 이름 때문에 오류가 발생할 수 있다.

    그래서 이번에는 처음 받은 데이터 안에 있는
    country.name과 countryiso3code를 바로 사용한다.
    """

    response = requests.get(
        WORLD_BANK_URL,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    # World Bank API의 첫 번째 항목은 페이지 정보이고,
    # 실제 데이터는 두 번째 항목이다.
    if len(data) < 2:
        raise ValueError(
            "World Bank에서 인구 데이터를 받지 못했습니다."
        )

    rows = data[1]

    result = []

    for row in rows:

        # ISO3 국가 코드
        iso3 = row.get(
            "countryiso3code"
        )

        # 국가 이름
        country_info = row.get(
            "country",
            {}
        )

        country_name = country_info.get(
            "value",
            ""
        )

        # 연도
        year = row.get(
            "date"
        )

        # 65세 이상 인구 비율
        value = row.get(
            "value"
        )

        # 필요한 값이 없는 행은 제외
        if not iso3:
            continue

        if not country_name:
            continue

        if value is None:
            continue

        result.append(
            {
                "ISO3": str(iso3).strip(),
                "국가": country_name,
                "연도": int(year),
                "고령화율": float(value)
            }
        )

    world = pd.DataFrame(result)

    if world.empty:
        raise ValueError(
            "세계 인구 데이터를 만들지 못했습니다."
        )

    # -----------------------------------------------------
    # World Bank에는 국가뿐 아니라
    # 지역/소득그룹 등의 집계자료도 포함될 수 있다.
    #
    # 실제 국가 지도를 그리기 위해
    # ISO3 코드가 존재하는 자료만 사용한다.
    # -----------------------------------------------------

    world["ISO3"] = (
        world["ISO3"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    world = world[
        world["ISO3"].str.len() == 3
    ].copy()

    # -----------------------------------------------------
    # 각 국가에서 가장 최신 연도의 자료를 선택한다.
    #
    # 국가마다 최신 자료가 서로 다를 수 있으므로
    # 전체에서 단 하나의 연도를 선택하지 않고
    # 국가별 최신 연도를 사용한다.
    # -----------------------------------------------------

    world = (
        world
        .sort_values(
            ["ISO3", "연도"]
        )
        .groupby(
            "ISO3",
            as_index=False
        )
        .tail(1)
        .copy()
    )

    # 표시용 소수점
    world["고령화율"] = (
        world["고령화율"]
        .round(2)
    )

    # 화면에 표시할 최신 연도
    latest_year = int(
        world["연도"].max()
    )

    return world, latest_year


# =========================================================
# 4. 한국 인구 데이터 불러오기
# =========================================================

@st.cache_data
def load_korea_population():
    """
    한국 읍·면·동 인구 데이터를 불러온다.
    """

    response = requests.get(
        KOREA_POPULATION_URL,
        timeout=60
    )

    response.raise_for_status()

    # gzip 압축 해제
    data = gzip.decompress(
        response.content
    )

    # '코드'는 계산하는 숫자가 아니라
    # 행정구역을 구분하는 코드이므로 문자열로 읽는다.
    df = pd.read_csv(
        io.BytesIO(data),
        dtype={"코드": str}
    )

    return df


# =========================================================
# 5. 한국 GeoJSON 불러오기
# =========================================================

@st.cache_data
def load_korea_geojson():

    response = requests.get(
        KOREA_GEOJSON_URL,
        timeout=60
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# 6. 한국 시군구별 고령화율 계산
# =========================================================

@st.cache_data
def make_korea_data(df):

    df = df.copy()

    # 행정동 코드는 반드시 문자열
    df["코드"] = (
        df["코드"]
        .astype(str)
        .str.strip()
    )

    # 코드 앞 5자리가 시군구 코드
    df["시군구코드"] = (
        df["코드"]
        .str[:5]
    )

    # 연도 숫자 변환
    df["연도"] = pd.to_numeric(
        df["연도"],
        errors="coerce"
    )

    # 가장 최신 연도 선택
    latest_year = int(
        df["연도"].max()
    )

    latest = df[
        df["연도"] == latest_year
    ].copy()

    # -----------------------------------------------------
    # 전체 연령의 '계_' 열 찾기
    # 예:
    # 계_0세
    # 계_1세
    # ...
    # 계_65세
    # ...
    # 계_100세 이상
    # -----------------------------------------------------

    age_columns = [
        col
        for col in latest.columns
        if col.startswith("계_")
    ]

    # 65세 이상 열 찾기
    elderly_columns = []

    for col in age_columns:

        age_text = (
            col
            .replace("계_", "")
            .strip()
        )

        if age_text == "100세 이상":

            elderly_columns.append(col)

        else:

            try:

                age = int(
                    age_text.replace(
                        "세",
                        ""
                    )
                )

                if age >= 65:
                    elderly_columns.append(
                        col
                    )

            except ValueError:

                # 숫자로 해석할 수 없는 열은 무시
                pass

    if not elderly_columns:
        raise ValueError(
            "65세 이상 인구 열을 찾지 못했습니다."
        )

    # 숫자형으로 변환
    for col in age_columns:

        latest[col] = pd.to_numeric(
            latest[col],
            errors="coerce"
        ).fillna(0)

    # 전체 인구
    latest["전체인구"] = (
        latest[age_columns]
        .sum(axis=1)
    )

    # 65세 이상 인구
    latest["65세이상인구"] = (
        latest[elderly_columns]
        .sum(axis=1)
    )

    # -----------------------------------------------------
    # 읍·면·동 → 시군구로 합산
    # -----------------------------------------------------

    sigungu = (
        latest
        .groupby(
            "시군구코드",
            as_index=False
        )
        .agg(
            전체인구=(
                "전체인구",
                "sum"
            ),
            **{
                "65세이상인구": (
                    "65세이상인구",
                    "sum"
                )
            }
        )
    )

    # 인구가 0인 지역 제외
    sigungu = sigungu[
        sigungu["전체인구"] > 0
    ].copy()

    # 고령화율 계산
    sigungu["고령화율"] = (
        sigungu["65세이상인구"]
        / sigungu["전체인구"]
        * 100
    )

    sigungu["고령화율"] = (
        sigungu["고령화율"]
        .round(2)
    )

    return sigungu, latest_year


# =========================================================
# 7. 한국 GeoJSON 지역 정보
# =========================================================

@st.cache_data
def get_korea_geo_info(geojson):

    rows = []

    for feature in geojson["features"]:

        properties = feature.get(
            "properties",
            {}
        )

        rows.append(
            {
                "시군구코드": str(
                    properties.get(
                        "코드",
                        ""
                    )
                ).strip(),

                "시군구": properties.get(
                    "시군구",
                    ""
                ),

                "시도": properties.get(
                    "시도",
                    ""
                )
            }
        )

    return pd.DataFrame(rows)


# =========================================================
# 8. 세계 지도 5단계 분류
# =========================================================

def classify_world_rate(rate):

    if rate < 7:

        return "7% 미만"

    elif rate < 14:

        return "7% 이상 ~ 14% 미만"

    elif rate < 21:

        return "14% 이상 ~ 21% 미만"

    elif rate < 28:

        return "21% 이상 ~ 28% 미만"

    else:

        return "28% 이상"


# =========================================================
# 9. 세계 지도 만들기
# =========================================================

def make_world_map(world):

    world = world.copy()

    world["구간"] = (
        world["고령화율"]
        .apply(
            classify_world_rate
        )
    )

    categories = [
        "7% 미만",
        "7% 이상 ~ 14% 미만",
        "14% 이상 ~ 21% 미만",
        "21% 이상 ~ 28% 미만",
        "28% 이상"
    ]

    # 낮은 비율 → 옅은 색
    # 높은 비율 → 진한 색
    colors = {

        "7% 미만": "#FFF7BC",

        "7% 이상 ~ 14% 미만":
            "#FEC44F",

        "14% 이상 ~ 21% 미만":
            "#FE9929",

        "21% 이상 ~ 28% 미만":
            "#EC7014",

        "28% 이상":
            "#CC4C02"
    }

    fig = go.Figure()

    # 구간별로 하나의 레이어를 만든다.
    # 이렇게 하면 범례에도 5개 구간이 나타난다.
    for category in categories:

        selected = world[
            world["구간"] == category
        ]

        if selected.empty:
            continue

        customdata = selected[
            [
                "국가",
                "고령화율",
                "연도"
            ]
        ].fillna("").values

        fig.add_trace(
            go.Choropleth(

                # 국가 ISO3 코드 사용
                locations=selected["ISO3"],

                locationmode="ISO-3",

                # 같은 구간은 같은 색
                z=[1] * len(selected),

                colorscale=[
                    [0, colors[category]],
                    [1, colors[category]]
                ],

                showscale=False,

                marker=dict(
                    line=dict(
                        color="white",
                        width=0.5
                    )
                ),

                name=category,

                customdata=customdata,

                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "65세 이상 인구 비율: "
                    "%{customdata[1]:.2f}%<br>"
                    "자료 연도: "
                    "%{customdata[2]}"
                    "<extra></extra>"
                )
            )
        )

    # -----------------------------------------------------
    # 배경 지도 타일은 사용하지 않는다.
    # 국가 경계만 표시한다.
    # -----------------------------------------------------

    fig.update_geos(

        visible=False,

        projection_type="natural earth",

        showland=True,
        landcolor="white",

        showocean=True,
        oceancolor="white",

        showcountries=True,
        countrycolor="#cccccc"
    )

    fig.update_layout(

        height=650,

        margin=dict(
            l=0,
            r=0,
            t=10,
            b=10
        ),

        paper_bgcolor="white",
        plot_bgcolor="white",

        legend=dict(
            title="65세 이상 인구 비율",
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#cccccc",
            borderwidth=1
        )
    )

    return fig


# =========================================================
# 10. 한국 지도 만들기
# =========================================================

def make_korea_map(
    sigungu,
    geojson
):

    geo_info = get_korea_geo_info(
        geojson
    )

    # 반드시 시군구 코드로 연결
    map_data = geo_info.merge(
        sigungu,
        on="시군구코드",
        how="left"
    )

    categories = [
        "19% 미만",
        "19% 이상 ~ 23% 미만",
        "23% 이상 ~ 28% 미만",
        "28% 이상 ~ 38% 미만",
        "38% 이상"
    ]

    colors = {

        "19% 미만": "#FFF7BC",

        "19% 이상 ~ 23% 미만":
            "#FEC44F",

        "23% 이상 ~ 28% 미만":
            "#FE9929",

        "28% 이상 ~ 38% 미만":
            "#EC7014",

        "38% 이상":
            "#CC4C02"
    }

    def classify_korea(rate):

        if pd.isna(rate):
            return None

        if rate < 19:
            return "19% 미만"

        elif rate < 23:
            return "19% 이상 ~ 23% 미만"

        elif rate < 28:
            return "23% 이상 ~ 28% 미만"

        elif rate < 38:
            return "28% 이상 ~ 38% 미만"

        else:
            return "38% 이상"

    map_data["구간"] = (
        map_data["고령화율"]
        .apply(
            classify_korea
        )
    )

    fig = go.Figure()

    for category in categories:

        selected = map_data[
            map_data["구간"] == category
        ]

        if selected.empty:
            continue

        customdata = selected[
            [
                "시군구",
                "시도",
                "고령화율"
            ]
        ].fillna("").values

        fig.add_trace(
            go.Choropleth(

                geojson=geojson,

                featureidkey=(
                    "properties.코드"
                ),

                locations=selected[
                    "시군구코드"
                ],

                z=[1] * len(selected),

                colorscale=[
                    [0, colors[category]],
                    [1, colors[category]]
                ],

                showscale=False,

                marker=dict(
                    line=dict(
                        color="white",
                        width=0.7
                    )
                ),

                name=category,

                customdata=customdata,

                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    "시도: %{customdata[1]}<br>"
                    "65세 이상 인구 비율: "
                    "%{customdata[2]:.2f}%"
                    "<extra></extra>"
                )
            )
        )

    fig.update_geos(
        fitbounds="locations",
        visible=False
    )

    fig.update_layout(

        height=700,

        margin=dict(
            l=0,
            r=0,
            t=10,
            b=10
        ),

        paper_bgcolor="white",
        plot_bgcolor="white",

        legend=dict(
            title="65세 이상 인구 비율",
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255,255,255,0.9)",
            bordercolor="#cccccc",
            borderwidth=1
        )
    )

    return fig


# =========================================================
# 11. 데이터 불러오기
# =========================================================

try:

    # 세계 데이터
    world_df, world_year = (
        load_world_data()
    )

    # 한국 데이터
    korea_population = (
        load_korea_population()
    )

    korea_geojson = (
        load_korea_geojson()
    )

    korea_df, korea_year = (
        make_korea_data(
            korea_population
        )
    )

except Exception as e:

    st.error(
        "데이터를 불러오는 중 문제가 발생했습니다."
    )

    st.exception(e)

    st.stop()


# =========================================================
# 12. 전세계 지도
# =========================================================

st.header(
    f"1. 전세계 고령화 지도"
)

st.write(
    "각 국가의 전체 인구 중 65세 이상 인구가 "
    "차지하는 비율을 5단계로 나타냈다."
)

world_fig = make_world_map(
    world_df
)

st.plotly_chart(
    world_fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "scrollZoom": False
    }
)

st.caption(
    f"세계 데이터에서 국가별로 이용 가능한 가장 최신 자료를 사용했습니다. "
    f"전체 데이터에서 확인되는 최신 연도: {world_year}년"
)


# =========================================================
# 13. 전세계 TOP / BOTTOM 10
# =========================================================

st.subheader(
    "전세계 국가별 고령화율"
)

world_ranking = (
    world_df
    .sort_values(
        "고령화율",
        ascending=False
    )
    .copy()
)

world_top10 = (
    world_ranking
    .head(10)
    [
        [
            "국가",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

world_top10.index += 1

world_bottom10 = (
    world_ranking
    .sort_values(
        "고령화율",
        ascending=True
    )
    .head(10)
    [
        [
            "국가",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

world_bottom10.index += 1

world_top10["고령화율"] = (
    world_top10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)

world_bottom10["고령화율"] = (
    world_bottom10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)

col1, col2 = st.columns(2)

with col1:

    st.markdown(
        "#### 고령화율 높은 국가 10개"
    )

    st.dataframe(
        world_top10,
        use_container_width=True,
        height=400
    )

with col2:

    st.markdown(
        "#### 고령화율 낮은 국가 10개"
    )

    st.dataframe(
        world_bottom10,
        use_container_width=True,
        height=400
    )


# =========================================================
# 14. 대한민국 시군구 지도
# =========================================================

st.header(
    f"2. 대한민국 시군구 고령화 지도"
)

st.write(
    "한국은 읍·면·동 인구를 행정동 코드 앞 5자리 기준으로 "
    "시군구에 합산하여 표시했다."
)

korea_fig = make_korea_map(
    korea_df,
    korea_geojson
)

st.plotly_chart(
    korea_fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "scrollZoom": False
    }
)

st.caption(
    f"한국 데이터 최신 연도: {korea_year}년"
)


# =========================================================
# 15. 한국 시군구 TOP / BOTTOM 10
# =========================================================

st.subheader(
    "대한민국 시군구별 고령화율"
)

korea_geo_info = (
    get_korea_geo_info(
        korea_geojson
    )
)

korea_ranking = korea_df.merge(
    korea_geo_info,
    on="시군구코드",
    how="left"
)

korea_ranking = korea_ranking[
    korea_ranking["고령화율"].notna()
].copy()


# 높은 지역 10개
korea_top10 = (
    korea_ranking
    .sort_values(
        "고령화율",
        ascending=False
    )
    .head(10)
    [
        [
            "시도",
            "시군구",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

korea_top10.index += 1


# 낮은 지역 10개
korea_bottom10 = (
    korea_ranking
    .sort_values(
        "고령화율",
        ascending=True
    )
    .head(10)
    [
        [
            "시도",
            "시군구",
            "고령화율"
        ]
    ]
    .reset_index(drop=True)
)

korea_bottom10.index += 1


korea_top10["고령화율"] = (
    korea_top10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)

korea_bottom10["고령화율"] = (
    korea_bottom10["고령화율"]
    .map(
        lambda x:
        f"{x:.2f}%"
    )
)


col1, col2 = st.columns(2)

with col1:

    st.markdown(
        "#### 고령화율 높은 시군구 10개"
    )

    st.dataframe(
        korea_top10,
        use_container_width=True,
        height=400
    )

with col2:

    st.markdown(
        "#### 고령화율 낮은 시군구 10개"
    )

    st.dataframe(
        korea_bottom10,
        use_container_width=True,
        height=400
    )


# =========================================================
# 16. 데이터 출처
# =========================================================

st.divider()

st.subheader(
    "데이터 출처"
)

st.caption(
    "세계: World Bank, "
    "Population ages 65 and above (% of total population), "
    "UN World Population Prospects 기반"
)

st.caption(
    "한국: greatsong/modudata "
    "전국 읍·면·동 인구 및 시군구 경계 데이터"
)
