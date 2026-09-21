import gzip
import io
import json

import pandas as pd
import requests
import streamlit as st
import plotly.graph_objects as go


# ============================================================
# 1. 기본 설정
# ============================================================

st.set_page_config(
    page_title="세계·한국 고령화 지도",
    page_icon="🌍",
    layout="wide"
)

st.title("🌍 세계·한국 고령화 지도")
st.write(
    "세계 각국의 65세 이상 인구 비율과 한국 시군구별 고령화율을 "
    "한눈에 확인할 수 있는 지도입니다."
)


# ============================================================
# 2. 데이터 주소
# ============================================================

POPULATION_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/main/"
    "data/population_yearly.csv.gz"
)

GEOJSON_URL = (
    "https://raw.githubusercontent.com/greatsong/modudata/main/"
    "data/boundaries/sigungu_kr.geojson"
)

WORLD_BANK_URL = (
    "https://api.worldbank.org/v2/country/all/indicator/"
    "SP.POP.65UP.TO.ZS"
    "?format=json&per_page=20000"
)


# ============================================================
# 3. 한국 인구 데이터 불러오기
# ============================================================

@st.cache_data
def load_population_data():

    response = requests.get(
        POPULATION_URL,
        timeout=60
    )

    response.raise_for_status()

    # gzip으로 압축된 CSV 읽기
    with gzip.GzipFile(fileobj=io.BytesIO(response.content)) as gz:
        df = pd.read_csv(
            gz,
            dtype={"코드": str}
        )

    return df


# ============================================================
# 4. 한국 지도 GeoJSON 불러오기
# ============================================================

@st.cache_data
def load_geojson():

    response = requests.get(
        GEOJSON_URL,
        timeout=60
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# 5. 세계 고령화 데이터 불러오기
# ============================================================

@st.cache_data
def load_world_data():

    response = requests.get(
        WORLD_BANK_URL,
        timeout=60
    )

    response.raise_for_status()

    data = response.json()

    if len(data) < 2:
        raise ValueError(
            "World Bank에서 데이터를 받지 못했습니다."
        )

    rows = data[1]

    result = []

    for row in rows:

        iso3 = row.get("countryiso3code")

        country_info = row.get(
            "country",
            {}
        )

        country_name = country_info.get(
            "value",
            ""
        )

        year = row.get("date")

        value = row.get("value")

        if (
            not iso3
            or not country_name
            or value is None
        ):
            continue

        result.append(
            {
                "ISO3": str(iso3).strip().upper(),
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

    # ISO3 코드가 정상적인 국가만 사용
    world = world[
        world["ISO3"].str.len() == 3
    ].copy()

    # 국가별 가장 최근 자료만 사용
    world = (
        world
        .sort_values(["ISO3", "연도"])
        .groupby("ISO3", as_index=False)
        .tail(1)
        .copy()
    )

    world["고령화율"] = world[
        "고령화율"
    ].round(2)

    latest_year = int(
        world["연도"].max()
    )

    return world, latest_year


# ============================================================
# 6. 세계 고령화 지도 만들기
# ============================================================

def make_world_map(world):

    # 고령화율에 따른 5단계 구분
    def get_level(value):

        if value < 7:
            return 0
        elif value < 14:
            return 1
        elif value < 21:
            return 2
        elif value < 28:
            return 3
        else:
            return 4

    selected = world.copy()

    selected["등급"] = selected[
        "고령화율"
    ].apply(get_level)

    # 단계별 색상
    colors = [
        "#f7fbff",
        "#c6dbef",
        "#6baed6",
        "#2171b5",
        "#08306b"
    ]

    labels = [
        "7% 미만",
        "7% 이상 ~ 14% 미만",
        "14% 이상 ~ 21% 미만",
        "21% 이상 ~ 28% 미만",
        "28% 이상"
    ]

    fig = go.Figure()

    # 5단계별로 따로 그려서 범례를 만들기
    for level in range(5):

        part = selected[
            selected["등급"] == level
        ].copy()

        if part.empty:
            continue

        customdata = part[
            [
                "ISO3",
                "국가",
                "고령화율",
                "연도"
            ]
        ].fillna("").values

        fig.add_trace(
            go.Choropleth(
                locations=part["ISO3"],
                z=[level] * len(part),
                locationmode="ISO-3",
                colorscale=[
                    [0, colors[level]],
                    [1, colors[level]]
                ],
                showscale=False,
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "고령화율: %{customdata[2]}%<br>"
                    "자료 연도: %{customdata[3]}"
                    "<extra></extra>"
                ),
                name=labels[level]
            )
        )

    fig.update_layout(
        title="세계 65세 이상 인구 비율",
        geo=dict(
            showframe=False,
            showcoastlines=True,
            projection_type="natural earth",
            showland=True,
            showcountries=True,
            bgcolor="rgba(0,0,0,0)"
        ),
        margin=dict(
            l=0,
            r=0,
            t=60,
            b=0
        ),
        legend=dict(
            title="고령화율",
            orientation="h",
            yanchor="bottom",
            y=0.01,
            xanchor="center",
            x=0.5
        )
    )

    return fig


# ============================================================
# 7. 선택한 나라의 연예인 정보 가져오기
# ============================================================

@st.cache_data(ttl=3600)
def get_celebrities(iso3):

    query = f"""
    SELECT ?person ?personLabel ?image WHERE {{

      ?country wdt:P297 "{iso3}" .

      ?person wdt:P27 ?country .

      ?person wdt:P18 ?image .

      {{
        ?person wdt:P106 wd:Q33999 .
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q177220 .
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q639669 .
      }}
      UNION
      {{
        ?person wdt:P106 wd:Q4610556 .
      }}

      SERVICE wikibase:label {{
        bd:serviceParam
          wikibase:language "ko,en" .
      }}
    }}

    LIMIT 8
    """

    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": (
            "Streamlit-Aging-Map/1.0 "
            "(educational project)"
        )
    }

    response = requests.get(
        "https://query.wikidata.org/sparql",
        params={
            "query": query,
            "format": "json"
        },
        headers=headers,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    results = []

    bindings = (
        data
        .get("results", {})
        .get("bindings", [])
    )

    for item in bindings:

        name = (
            item
            .get("personLabel", {})
            .get("value", "")
        )

        image = (
            item
            .get("image", {})
            .get("value", "")
        )

        if name and image:

            results.append(
                {
                    "name": name,
                    "image": image
                }
            )

    return results


# ============================================================
# 8. 한국 데이터 가공
# ============================================================

@st.cache_data
def make_korea_data(df):

    # 전체 인구 컬럼
    total_columns = [
        col
        for col in df.columns
        if col.startswith("계_")
    ]

    # 65세 이상 인구 컬럼
    elderly_columns = []

    for age in range(65, 101):

        column = f"계_{age}세"

        if column in df.columns:
            elderly_columns.append(column)

    if "계_100세 이상" in df.columns:
        elderly_columns.append(
            "계_100세 이상"
        )

    # 시군구 코드 = 읍면동 코드의 앞 5자리
    df = df.copy()

    df["시군구코드"] = (
        df["코드"]
        .astype(str)
        .str[:5]
    )

    # 최신 연도 선택
    latest_year = int(
        df["year"].max()
    )

    latest = df[
        df["year"] == latest_year
    ].copy()

    # 숫자로 변환
    for col in total_columns:
        latest[col] = pd.to_numeric(
            latest[col],
            errors="coerce"
        ).fillna(0)

    for col in elderly_columns:
        latest[col] = pd.to_numeric(
            latest[col],
            errors="coerce"
        ).fillna(0)

    # 읍면동별 인구를 시군구 단위로 합산
    korea = (
        latest
        .groupby(
            [
                "시도",
                "시군구",
                "시군구코드"
            ],
            as_index=False
        )[total_columns + elderly_columns]
        .sum()
    )

    korea["전체인구"] = korea[
        total_columns
    ].sum(axis=1)

    korea["65세이상인구"] = korea[
        elderly_columns
    ].sum(axis=1)

    korea["고령화율"] = (
        korea["65세이상인구"]
        / korea["전체인구"]
        * 100
    )

    korea["고령화율"] = (
        korea["고령화율"]
        .replace(
            [float("inf"), -float("inf")],
            0
        )
        .fillna(0)
        .round(2)
    )

    return korea, latest_year


# ============================================================
# 9. 한국 지도 만들기
# ============================================================

def make_korea_map(korea, geojson):

    fig = go.Figure()

    # 고령화율 단계
    def get_level(value):

        if value < 19:
            return 0
        elif value < 23:
            return 1
        elif value < 28:
            return 2
        elif value < 38:
            return 3
        else:
            return 4

    colors = [
        "#f7fbff",
        "#c6dbef",
        "#6baed6",
        "#2171b5",
        "#08306b"
    ]

    labels = [
        "19% 미만",
        "19% 이상 ~ 23% 미만",
        "23% 이상 ~ 28% 미만",
        "28% 이상 ~ 38% 미만",
        "38% 이상"
    ]

    korea = korea.copy()

    korea["등급"] = (
        korea["고령화율"]
        .apply(get_level)
    )

    # 지도 경계의 코드 목록
    geo_features = geojson.get(
        "features",
        []
    )

    for level in range(5):

        part = korea[
            korea["등급"] == level
        ].copy()

        if part.empty:
            continue

        customdata = part[
            [
                "시도",
                "시군구",
                "고령화율"
            ]
        ].values

        fig.add_trace(
            go.Choroplethmapbox(
                geojson={
                    "type": "FeatureCollection",
                    "features": [
                        feature
                        for feature in geo_features
                        if str(
                            feature.get(
                                "properties",
                                {}
                            ).get(
                                "코드",
                                ""
                            )
                        ).zfill(5)
                        in set(
                            part["시군구코드"]
                        )
                    ]
                },
                locations=part["시군구코드"],
                z=[level] * len(part),
                featureidkey=(
                    "properties.코드"
                ),
                colorscale=[
                    [0, colors[level]],
                    [1, colors[level]]
                ],
                showscale=False,
                customdata=customdata,
                hovertemplate=(
                    "<b>%{customdata[1]}</b><br>"
                    "시도: %{customdata[0]}<br>"
                    "고령화율: %{customdata[2]}%"
                    "<extra></extra>"
                ),
                name=labels[level]
            )
        )

    fig.update_layout(
        mapbox=dict(
            style="white-bg",
            zoom=6,
            center=dict(
                lat=36.3,
                lon=127.8
            )
        ),
        margin=dict(
            l=0,
            r=0,
            t=60,
            b=0
        ),
        legend=dict(
            title="고령화율",
            orientation="h",
            yanchor="bottom",
            y=0.01,
            xanchor="center",
            x=0.5
        )
    )

    return fig


# ============================================================
# 10. 데이터 불러오기
# ============================================================

try:

    population_df = (
        load_population_data()
    )

    geojson_data = (
        load_geojson()
    )

    world_df, world_year = (
        load_world_data()
    )

    korea_df, korea_year = (
        make_korea_data(
            population_df
        )
    )

except Exception as e:

    st.error(
        "데이터를 불러오는 중 오류가 발생했습니다."
    )

    st.exception(e)

    st.stop()


# ============================================================
# 11. 세계 지도
# ============================================================

st.header("🌍 세계 고령화 지도")

st.caption(
    f"각 국가에서 확인 가능한 가장 최근 연도의 "
    f"65세 이상 인구 비율을 표시합니다."
)

world_fig = make_world_map(
    world_df
)


# ============================================================
# 12. 세계 지도 클릭 이벤트
# ============================================================

world_event = st.plotly_chart(
    world_fig,
    use_container_width=True,
    key="world_aging_map",
    on_select="rerun",
    selection_mode="points",
    config={
        "displaylogo": False,
        "scrollZoom": False
    }
)


selected_iso3 = None
selected_country = None


try:

    points = (
        world_event
        .selection
        .points
    )

    if points:

        point = points[0]

        customdata = (
            point.get("customdata")
        )

        if customdata:

            selected_iso3 = (
                customdata[0]
            )

            selected_country = (
                customdata[1]
            )

except Exception:
    pass


# ============================================================
# 13. 선택한 나라의 연예인 사진 표시
# ============================================================

if selected_iso3:

    st.subheader(
        f"🎬 {selected_country}의 연예인"
    )

    st.caption(
        "지도에서 선택한 국가와 관련된 "
        "배우·가수·음악가·모델 중 "
        "Wikidata에 사진이 등록된 인물을 표시합니다."
    )

    try:

        celebrities = get_celebrities(
            selected_iso3
        )

        if celebrities:

            # 최대 4명씩 한 줄에 표시
            for start in range(
                0,
                len(celebrities),
                4
            ):

                row = celebrities[
                    start:start + 4
                ]

                columns = st.columns(
                    len(row)
                )

                for column, person in zip(
                    columns,
                    row
                ):

                    with column:

                        st.image(
                            person["image"],
                            use_container_width=True
                        )

                        st.caption(
                            person["name"]
                        )

        else:

            st.info(
                "이 국가에서 사진이 등록된 "
                "연예인 정보를 찾지 못했습니다."
            )

    except Exception as e:

        st.warning(
            "연예인 정보를 불러오지 못했습니다."
        )

        st.caption(
            f"오류 내용: {e}"
        )


else:

    st.info(
        "👆 세계 지도에서 국가를 클릭하면 "
        "해당 국가의 연예인 사진을 볼 수 있습니다."
    )


# ============================================================
# 14. 한국 시군구 고령화 지도
# ============================================================

st.divider()

st.header("🇰🇷 한국 시군구별 고령화 지도")

st.caption(
    f"{korea_year}년 기준 · "
    "65세 이상 인구 비율"
)

korea_fig = make_korea_map(
    korea_df,
    geojson_data
)

st.plotly_chart(
    korea_fig,
    use_container_width=True,
    config={
        "displaylogo": False,
        "scrollZoom": True
    }
)


# ============================================================
# 15. 한국 시군구 고령화율 순위
# ============================================================

st.subheader(
    f"📊 {korea_year}년 시군구 고령화율 순위"
)


# 고령화율이 높은 지역 TOP 10
korea_top10 = (
    korea_df[
        [
            "시도",
            "시군구",
            "전체인구",
            "65세이상인구",
            "고령화율"
        ]
    ]
    .sort_values(
        "고령화율",
        ascending=False
    )
    .head(10)
    .reset_index(drop=True)
)

korea_top10.index += 1


# 고령화율이 낮은 지역 TOP 10
korea_bottom10 = (
    korea_df[
        [
            "시도",
            "시군구",
            "전체인구",
            "65세이상인구",
            "고령화율"
        ]
    ]
    .sort_values(
        "고령화율",
        ascending=True
    )
    .head(10)
    .reset_index(drop=True)
)

korea_bottom10.index += 1


# ============================================================
# 16. 순위 테이블 표시
# ============================================================

left_column, right_column = (
    st.columns(2)
)


with left_column:

    st.markdown(
        "### 🔴 고령화율이 높은 지역"
    )

    st.dataframe(
        korea_top10,
        use_container_width=True
    )


with right_column:

    st.markdown(
        "### 🔵 고령화율이 낮은 지역"
    )

    st.dataframe(
        korea_bottom10,
        use_container_width=True
    )


# ============================================================
# 17. 데이터 설명
# ============================================================

st.divider()

st.caption(
    "세계 데이터: World Bank "
    "(Population ages 65 and above, % of total)"
)

st.caption(
    "한국 데이터: 행정구역별 연령 인구 자료"
)

st.caption(
    "세계 지도에서 국가를 클릭하면 "
    "Wikidata에 등록된 해당 국가의 연예인 사진을 조회합니다."
)
